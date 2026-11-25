"""Human stops (module 11): decision files, the one answer check, and the gate checks that read them.

A stop writes decisions/<stage>.<n>.yaml. Every answer goes through record(), and every reader goes through
evaluate(). This module never routes a run or starts an engine: it returns an Outcome, and module 6B and the
drivers do the rest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from . import state
from .atomic import write_text_atomic
from .errors import FactoryError
from .types import Channel, GateContext, GateResult, GateSpec, Run
from .validate import validate
from .yamlio import load_yaml

StopKind = Literal["approval", "decision", "triage", "blocked"]
Packet = dict[str, Any]

APPROVAL_OPTIONS = frozenset({"approve", "rework", "reject"})
BLOCKED_OPTIONS = frozenset({"retry", "goto", "skip", "abort"})  # module 11: a blocked run offers all four (owner decision, 2026-11-24)


@dataclass
class Outcome:
    status: str  # approved | rework | reject | question | pending | rejected
    choices: dict[str, str]
    questions: dict[str, str]
    notes: str
    code: str | None
    message: str | None


def decision_path(run_dir: Path, stage: str, visit: int) -> Path:
    return run_dir / "decisions" / f"{stage}.{visit}.yaml"


def page_path(run_dir: Path, stage: str, visit: int) -> Path:
    return run_dir / "decisions" / f"{stage}.{visit}.html"


def hash_packet(packet: Packet) -> str:
    """The packet's sha: 8 hex characters of SHA-256 over its canonical JSON, without the sha field."""
    body = {k: v for k, v in packet.items() if k != "sha"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def latest_visit(run: Run, stage: str) -> int:
    """The open visit of a stage: the highest visit recorded for it. --stage on decide, open and check defaults to it."""
    return max((s.visit for s in run.stages if s.id == stage), default=1)


def triage_packet(candidates: list[tuple[str, str, str]]) -> Packet:
    """The triage packet: one decision whose options are the candidate workflows.

    Each candidate is (workflow id, name, reason). Module 4 builds it, because only triage knows the candidates.
    The packet schema allows two to four options.
    """
    options = [{"id": wid, "name": name, "flow": [f"workflow:{wid}"], "pros": [reason], "cons": []}
               for wid, name, reason in candidates]
    return {"stage": "_triage", "sha": "", "decisions": [{
        "id": "D1",
        "title": "Which workflow runs this request",
        "question": "The rules could not pick one workflow. Which one should run?",
        "context": {
            "what": "Triage found no single workflow for this request.",
            "example": "A request titled 'Fix login' matches both a bug fix and a feature workflow.",
            "terms": {},
        },
        "compare": {"a": candidates[0][0] if candidates else "", "b": candidates[1][0] if len(candidates) > 1 else "",
                    "rows": [], "choose_a_if": candidates[0][2] if candidates else "",
                    "choose_b_if": candidates[1][2] if len(candidates) > 1 else ""},
        "recommend": candidates[0][0] if candidates else "",
        "why": "The first candidate is the closest match by the rules.",
        "options": options,
    }]}


def _approval_packet(stage: str) -> Packet:
    return {"stage": stage, "sha": "", "decisions": [{
        "id": "D1",
        "title": f"Approve {stage}",
        "question": f"Does the {stage} stage meet the request?",
        "context": {
            "what": f"The {stage} stage has finished and waits for your approval.",
            "example": "Approve moves the run on. Rework sends it back with your notes. Reject ends the run.",
            "terms": {},
        },
        "compare": {"a": "approve", "b": "reject", "rows": [],
                    "choose_a_if": "The stage output is right.", "choose_b_if": "The run should stop."},
        "recommend": "approve",
        "why": "Approve is the default once the stage output has passed its gates.",
        "options": [
            {"id": "approve", "name": "Approve", "flow": ["engine:Continue"],
             "pros": ["The run moves on"], "cons": ["Accepts the output as it is"]},
            {"id": "rework", "name": "Rework", "flow": ["human:Notes", "engine:Route back"],
             "pros": ["Your notes reach the stage"], "cons": ["Costs another pass"]},
            {"id": "reject", "name": "Reject", "flow": ["human:Reject", "engine:Abort"],
             "pros": ["Stops spend on this request"], "cons": ["The run ends"]},
        ],
    }]}


def _blocked_packet(stage: str) -> Packet:
    return {"stage": stage, "sha": "", "decisions": [{
        "id": "D1",
        "title": f"Blocked at {stage}",
        "question": f"What should happen to the run blocked at {stage}?",
        "context": {
            "what": "Retries or rework loops ran out, so the run waits for you.",
            "example": "A verify stage failed twice with the same test.",
            "terms": {},
        },
        "compare": {"a": "retry", "b": "abort", "rows": [],
                    "choose_a_if": "The failure looks temporary or your notes fix it.",
                    "choose_b_if": "The request should not continue."},
        "recommend": "retry",
        "why": "A retry costs one more attempt and keeps the work done so far.",
        "options": [
            {"id": "retry", "name": "Retry", "flow": ["engine:Run stage again"],
             "pros": ["Keeps the work done so far"], "cons": ["One more attempt"]},
            {"id": "goto", "name": "Send back to a stage", "flow": ["human:Pick a stage", "engine:Run from there"],
             "pros": ["Reruns the stage that is wrong, not the one that failed"], "cons": ["Work after that stage is redone"]},
            {"id": "skip", "name": "Skip a gate", "flow": ["human:Name the gate", "engine:Pass it on record"],
             "pros": ["Moves a stuck run on when the gate is wrong"], "cons": ["The gate's check is not made"]},
            {"id": "abort", "name": "Abort", "flow": ["human:Abort", "engine:Clean up"],
             "pros": ["Stops spend"], "cons": ["The request is not delivered"]},
        ],
    }]}


def _blank_decision() -> dict:
    return {"status": "pending", "choices": {}, "questions": {}, "notes": "", "by": None, "channel": None, "at": None}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _answered(dec: dict) -> bool:
    return dec["status"] != "pending" or bool(dec["choices"]) or bool(dec["questions"])


def _options(packet: Packet, decision_id: str) -> list[str]:
    for d in packet["decisions"]:
        if d["id"] == decision_id:
            return [o["id"] for o in d["options"]]
    return []


def _check_packet_rules(packet: Packet) -> None:
    """Rules the schema cannot state: unique ids, and a recommendation that is one of the options."""
    ids = [d["id"] for d in packet["decisions"]]
    if len(ids) != len(set(ids)):
        raise FactoryError("config.invalid", f"packet {packet['stage']}: decision ids repeat",
                           hint="give each decision in the packet its own id")
    for d in packet["decisions"]:
        options = [o["id"] for o in d["options"]]
        if len(options) != len(set(options)):
            raise FactoryError("config.invalid", f"decision {d['id']}: option ids repeat",
                               hint="give each option its own id")
        if d["recommend"] not in options:
            raise FactoryError("config.invalid", f"decision {d['id']}: recommend {d['recommend']!r} is not an option",
                               hint="name one of the option ids as recommend")


def _template(kind: StopKind, stage: str) -> Packet:
    if kind == "approval":
        return _approval_packet(stage)
    if kind == "blocked":
        return _blocked_packet(stage)
    raise FactoryError("decision.no_packet", f"a {kind} stop at {stage} needs a packet from its skill or caller",
                       hint="build the packet with triage_packet, or pass the skill's packet to request")


def _parse(raw: str, path: Path) -> dict:
    doc = load_yaml(raw, file=str(path))
    if not isinstance(doc, dict):
        raise FactoryError("config.invalid", f"{path}: the top level must be a mapping",
                           hint="write the packet and decision blocks")
    validate(doc, "decision", file=str(path))
    return doc


def read_decision(run_dir: Path, stage: str, visit: int) -> dict:
    """The decision file, checked against its schema. Raises when it is missing or invalid."""
    path = decision_path(run_dir, stage, visit)
    if not path.is_file():
        raise FactoryError("decision.not_requested", f"no decision file for {stage} visit {visit}",
                           hint="the engine writes it when the stop begins")
    return _parse(path.read_text(), path)


def try_read(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return _parse(path.read_text(), path)
    except (FactoryError, UnicodeDecodeError):
        return None


def _dump(doc: dict) -> str:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False)


def request(run_dir: Path, stage: str, visit: int, *, kind: StopKind, packet: Packet | None = None) -> str:
    """Write the decision file for a stop and render its page; return the packet sha.

    The same packet keeps any answer already recorded. A new packet resets the file to pending. When it replaces
    an answer, decision_invalidated is logged too. A failed page render leaves the file usable; its error is kept
    on the decision_requested event.
    """
    body = {k: v for k, v in (packet or _template(kind, stage)).items() if k != "sha"}
    sha = hash_packet(body)
    full: Packet = {**body, "sha": sha}
    validate(full, "packet", file=f"{stage} packet")  # a packet missing a field the picker shows fails here
    _check_packet_rules(full)

    path = decision_path(run_dir, stage, visit)
    old = try_read(path)
    if old is not None and old["packet"]["sha"] == sha:
        if not page_path(run_dir, stage, visit).is_file():
            _render(run_dir, stage, visit)
        return sha

    answered = old is not None and _answered(old["decision"])
    write_text_atomic(path, _dump({"packet": full, "decision": _blank_decision()}))
    if answered:
        state.append_event(run_dir, "decision_invalidated", stage=stage, visit=visit, packet_sha=sha,
                           previous_sha=old["packet"]["sha"])
    page_error = _render(run_dir, stage, visit)
    state.append_event(run_dir, "decision_requested", stage=stage, visit=visit, packet_sha=sha, kind=kind,
                       page_error=page_error)
    state.append_event(run_dir, "attention_requested", stage=stage, visit=visit, kind=kind, packet_sha=sha)
    return sha


def _render(run_dir: Path, stage: str, visit: int) -> str | None:
    """A failed render never blocks the stop: the YAML file stays usable and the error is kept on the event."""
    from .page import render_page  # lazy: page.py reads this module

    try:
        render_page(run_dir, stage, visit)
    except (FactoryError, OSError) as e:
        return getattr(e, "message", str(e))
    return None


# A blocked run's goto and skip answers carry their target as a second choice in the same file (owner decision,
# 2026-11-24): `D1.target` names the stage a goto sends the run to, `D1.gate` the gate a skip passes.
TARGET_KEYS = {"goto": "target", "skip": "gate"}


def _choice_problems(packet: Packet, choices: dict[str, str], *, require_all: bool) -> list[str]:
    ids = [d["id"] for d in packet["decisions"]]
    problems = []
    for key, value in choices.items():
        decision_id, _, sub = key.partition(".")
        if decision_id not in ids:
            problems.append(f"{decision_id} is not a decision in this packet")
        elif sub:
            problems += _target_problem(packet, decision_id, sub, value, choices)
        elif value not in _options(packet, decision_id):
            problems.append(f"{decision_id}: {value!r} is not one of its options")
    if require_all:
        problems += [f"{i}: no choice" for i in ids if i not in choices]
    for d in packet["decisions"]:
        pick = choices.get(d["id"])
        need = TARGET_KEYS.get(pick) if BLOCKED_OPTIONS == {o["id"] for o in d["options"]} else None
        if need and f"{d['id']}.{need}" not in choices:
            problems.append(f"{d['id']}: {pick} needs its {need}, as {d['id']}.{need}")
    return problems


def _target_problem(packet: Packet, decision_id: str, sub: str, value: str, choices: dict[str, str]) -> list[str]:
    """`D1.target` and `D1.gate` are accepted only on a blocked decision, only with the goto or skip that uses them."""
    d = next(x for x in packet["decisions"] if x["id"] == decision_id)
    if {o["id"] for o in d["options"]} != BLOCKED_OPTIONS:
        return [f"{decision_id}.{sub} is only for a blocked run"]
    if TARGET_KEYS.get(choices.get(decision_id)) != sub:
        return [f"{decision_id}.{sub} needs {decision_id} to be {'goto' if sub == 'target' else 'skip'}"]
    if not value.strip():
        return [f"{decision_id}.{sub} is empty"]
    return []


def record(run_dir: Path, stage: str, visit: int, *, packet_sha: str, choices: dict[str, str] | None = None,
           questions: dict[str, str] | None = None, notes: str = "", by: str, channel: Channel) -> Outcome:
    """Write an answer. Refuses a packet sha that is not the current packet's, and any unknown or missing choice.

    Every route ends here. A refused answer changes nothing, and the stop stays pending.
    """
    doc = read_decision(run_dir, stage, visit)
    packet, dec = doc["packet"], doc["decision"]
    if dec["status"] == "approved":
        raise FactoryError("decision.locked", f"the {stage} decision is approved and locked",
                           hint=f"run factory reopen {run_dir.name} --stage {stage} to change it")
    current = hash_packet(packet)  # the packet as it is on disk, so an edited packet refuses an old sha
    if packet_sha != current:
        state.append_event(run_dir, "decision_rejected", stage=stage, visit=visit, reason="stale packet",
                           packet_sha=packet_sha, current_sha=current)
        raise FactoryError("decision.stale_packet",
                           f"the answer is for packet {packet_sha}, but the packet is now {current}",
                           hint=f"reopen the decision page with factory open {run_dir.name}, then answer again")
    picks = dict(choices or {})
    asked = {k: v.strip() for k, v in (questions or {}).items() if v.strip()}
    ids = [d["id"] for d in packet["decisions"]]
    problems = _choice_problems(packet, picks, require_all=not asked)
    problems += [f"{k} is not a decision in this packet" for k in asked if k not in ids]
    if problems:
        state.append_event(run_dir, "decision_rejected", stage=stage, visit=visit, reason="bad choice", problems=problems)
        raise FactoryError("decision.bad_choice", "; ".join(problems),
                           hint="answer every decision with one of its option ids")
    status = "question" if asked else "approved"
    doc["decision"] = {"status": status, "choices": picks, "questions": asked, "notes": notes, "by": by,
                       "channel": channel, "at": _now()}
    write_text_atomic(decision_path(run_dir, stage, visit), _dump(doc))
    state.append_event(run_dir, "decision_recorded", stage=stage, visit=visit, channel=channel, by=by, status=status)
    return evaluate(run_dir, stage, visit)


def evaluate(run_dir: Path, stage: str, visit: int) -> Outcome:
    """Read the decision file and say where the stop stands. Logs each outcome once per distinct file content."""
    path = decision_path(run_dir, stage, visit)
    if not path.is_file():
        return Outcome("pending", {}, {}, "", None, None)
    raw = path.read_bytes()
    content = hashlib.sha256(raw).hexdigest()
    try:
        doc = _parse(raw.decode(), path)
    except (FactoryError, UnicodeDecodeError) as e:
        code = e.code if isinstance(e, FactoryError) else "config.invalid"
        message = e.message if isinstance(e, FactoryError) else "the decision file is not UTF-8 text"
        return _rejected(run_dir, stage, visit, content, "decision_rejected", code, message)

    packet, dec = doc["packet"], doc["decision"]
    if hash_packet(packet) != packet["sha"]:
        if _answered(dec):
            return _rejected(run_dir, stage, visit, content, "decision_invalidated", "decision.stale_packet",
                             "the packet changed after an answer was recorded")
        return _rejected(run_dir, stage, visit, content, "decision_rejected", "decision.stale_packet",
                         "the packet was edited after it was requested")

    choices, questions, notes = dict(dec["choices"]), dict(dec["questions"]), dec["notes"]
    if dec["status"] == "pending":
        return Outcome("pending", choices, questions, notes, None, None)
    if dec["status"] == "question":
        return Outcome("question", choices, questions, notes, None, None)
    problems = _choice_problems(packet, choices, require_all=True)
    if problems:
        return _rejected(run_dir, stage, visit, content, "decision_rejected", "decision.bad_choice", "; ".join(problems))
    status = _outcome_for(packet, choices)
    _log_once(run_dir, "decision_approved", stage=stage, visit=visit, content=content, outcome=status)
    _log_once(run_dir, "attention_cleared", stage=stage, visit=visit, content=content)
    return Outcome(status, choices, questions, notes, None, None)


def _rejected(run_dir: Path, stage: str, visit: int, content: str, event: str, code: str, message: str) -> Outcome:
    _log_once(run_dir, event, stage=stage, visit=visit, content=content, code=code, reason=message)
    return Outcome("rejected", {}, {}, "", code, message)


def _log_once(run_dir: Path, event: str, *, stage: str, visit: int, content: str, **fields: Any) -> None:
    for rec in state.read_events(run_dir):
        if (rec.type == event and rec.data.get("content") == content and rec.data.get("stage") == stage
                and rec.data.get("visit") == visit):
            return
    state.append_event(run_dir, event, stage=stage, visit=visit, content=content, **fields)


def _outcome_for(packet: Packet, choices: dict[str, str]) -> str:
    """The route an answer means. Approval packets map to approve, rework or reject; blocked packets to retry or
    abort. Any other packet's answer is 'approved', and its caller decides what the choice means."""
    outcome = "approved"
    for d in packet["decisions"]:
        ids = {o["id"] for o in d["options"]}
        picked = choices[d["id"]]
        if ids == APPROVAL_OPTIONS:
            if picked == "reject":
                return "reject"
            if picked == "rework":
                outcome = "rework"
        elif ids == BLOCKED_OPTIONS and picked == "abort":
            return "reject"
    return outcome


def clear_answered_blocked(run_dir: Path, stage: str, visit: int) -> None:
    """Remove a blocked file that an earlier block's answer (retry, goto, skip or abort) already answered, so a new block at
    the same visit asks again. A pending file, or a file of another kind, is left alone."""
    path = decision_path(run_dir, stage, visit)
    doc = try_read(path)
    if doc is not None and kind_of(doc["packet"]) == "blocked" and _answered(doc["decision"]):
        path.unlink()


def reopen(run_dir: Path, stage: str, visit: int, *, by: str) -> None:
    """Unlock an approved decision so it can be answered again. A decision that is not approved is left alone."""
    doc = read_decision(run_dir, stage, visit)
    if doc["decision"]["status"] != "approved":
        return
    doc["decision"].update(status="pending", by=by, channel=None, at=_now())
    write_text_atomic(decision_path(run_dir, stage, visit), _dump(doc))
    state.append_event(run_dir, "decision_reopened", stage=stage, visit=visit, by=by)
    state.append_event(run_dir, "attention_requested", stage=stage, visit=visit, kind=kind_of(doc["packet"]),
                       packet_sha=doc["packet"]["sha"])


def kind_of(packet: Packet) -> str:
    """The kind of stop a packet is: triage, approval, blocked, or a decision from a skill."""
    if packet["stage"] == "_triage":
        return "triage"
    sets = [{o["id"] for o in d["options"]} for d in packet["decisions"]]
    if all(s == APPROVAL_OPTIONS for s in sets):
        return "approval"
    if all(s == BLOCKED_OPTIONS for s in sets):
        return "blocked"
    return "decision"


def _run_dir(run: Run) -> Path:
    return state.run_dir(state.factory_home(), run.repo_key, run.run_id)


def check_approved(spec: GateSpec, ctx: GateContext) -> GateResult:
    """decision-approved: the open visit of the gate's stage is approved."""
    visit = latest_visit(ctx.run, ctx.stage)
    out = evaluate(_run_dir(ctx.run), ctx.stage, visit)
    passed = out.status == "approved"
    return GateResult(passed=passed, gate="decision-approved", code="ok" if passed else "gate.decision_not_approved",
                      output_tail="" if passed else (out.message or out.status),
                      details={"stage": ctx.stage, "visit": visit, "outcome": out.status})


def check_packet_hash(spec: GateSpec, ctx: GateContext) -> GateResult:
    """packet-hash-matches: the packet in the decision file still hashes to the sha it was stamped with."""
    visit = latest_visit(ctx.run, ctx.stage)
    path = decision_path(_run_dir(ctx.run), ctx.stage, visit)
    doc = try_read(path)
    if doc is None:
        return GateResult(passed=False, gate="packet-hash-matches", code="gate.decision_missing",
                          output_tail=f"no readable decision file at {path}", details={"stage": ctx.stage, "visit": visit})
    current = hash_packet(doc["packet"])
    passed = current == doc["packet"]["sha"]
    return GateResult(passed=passed, gate="packet-hash-matches", code="ok" if passed else "gate.packet_hash_mismatch",
                      output_tail="" if passed else f"packet {doc['packet']['sha']} now hashes to {current}",
                      details={"stage": ctx.stage, "visit": visit, "sha": doc["packet"]["sha"]})


def check_build_stack(spec: GateSpec, ctx: GateContext) -> GateResult:
    """build-matches-stack: the build file names every entry in args['require'].

    The file is args['file'] when set, else the first of pom.xml and package.json that exists in the worktree.
    The workflow lists the stack's names in args, because the packet does not carry them.
    """
    require = [str(x) for x in spec.args.get("require", [])]
    names = [str(spec.args["file"])] if spec.args.get("file") else ["pom.xml", "package.json"]
    found = next((ctx.worktree / n for n in names if (ctx.worktree / n).is_file()), None)
    if found is None:
        return GateResult(passed=False, gate="build-matches-stack", code="gate.build_file_missing",
                          output_tail=f"none of {', '.join(names)} exists in the worktree", details={"files": names})
    text = found.read_text(errors="replace")
    missing = [r for r in require if r not in text]
    passed = not missing
    return GateResult(passed=passed, gate="build-matches-stack", code="ok" if passed else "gate.stack_mismatch",
                      output_tail="" if passed else f"{found.name} lacks: {', '.join(missing)}",
                      details={"file": found.name, "require": require, "missing": missing})
