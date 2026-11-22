"""The run summary (module 13): `summary.md`, filled by code from run state and artifacts.

It is the pull request body, the final issue comment and the record kept in the archive. Nothing here asks a worker:
every line comes from run.json, events.jsonl, the decision files, the notes, the usage report or merge.json.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from .atomic import read_jsonl, write_text_atomic
from .errors import FactoryError
from .gitops import git
from .state import read_events, read_run
from .types import Run
from .validate import validate
from .usage import ModelTotals, UsageReport
from .yamlio import load_yaml

MAX_FILES_LISTED = 20


def _base_ref(worktree: Path, hint: str | None) -> str | None:
    """The first of: the hinted base branch, the remote's default branch, main, master that exists as a ref."""
    names: list[str] = [hint] if hint else []
    head = git(worktree, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False).stdout.strip()
    if head:
        names.append(head.removeprefix("origin/"))
    names += ["main", "master"]
    for name in names:
        for ref in (f"origin/{name}", name):
            if git(worktree, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0:
                return ref
    return None


def diff_stats(worktree: Path, base: str | None = None) -> list[tuple[str, int, int]] | None:
    """(path, lines added, lines deleted) for what the run branch changes against its base. None when git cannot say.

    A binary file counts as 0 and 0. Renames are shown as a delete and an add, so a path is never `old => new`."""
    if not worktree.is_dir():
        return None
    ref = _base_ref(worktree, base)
    if ref is None:
        return None
    r = git(worktree, "diff", "--numstat", "--no-renames", f"{ref}...HEAD", check=False)
    if r.returncode != 0:
        return None
    out: list[tuple[str, int, int]] = []
    for line in r.stdout.splitlines():
        added, deleted, path = line.split("\t", 2)
        out.append((path, int(added) if added.isdigit() else 0, int(deleted) if deleted.isdigit() else 0))
    return out


def _yaml(path: Path) -> dict:
    try:
        doc = load_yaml(path.read_text(), file=str(path))
    except (FactoryError, OSError, UnicodeDecodeError):  # an unreadable decision file is left out, never a block
        return {}
    return doc if isinstance(doc, dict) else {}


def answered_decisions(run_dir: Path) -> list[tuple[str, str, dict, dict]]:
    """(stage, visit, packet, decision) for each decision file with an approved answer, in file order."""
    out = []
    for path in sorted((run_dir / "decisions").glob("*.yaml")):
        doc = _yaml(path)
        packet, dec = doc.get("packet") or {}, doc.get("decision") or {}
        if dec.get("status") == "approved":
            stage, _, rest = path.name.partition(".")
            out.append((stage, rest.split(".")[0], packet, dec))
    return out


def _what_changed(run: Run, base: str | None) -> str:
    stats = diff_stats(run.worktree, run.pr.base if run.pr else base)
    if stats is None:
        return "Not available: the run's worktree could not be read."
    if not stats:
        return "No files changed."
    names = [p for p, _, _ in stats]
    shown = ", ".join(names[:MAX_FILES_LISTED]) + (f" and {len(names) - MAX_FILES_LISTED} more" if len(names) > MAX_FILES_LISTED else "")
    plus, minus = sum(a for _, a, _ in stats), sum(d for _, _, d in stats)
    return f"{shown} ({len(names)} file{'s' if len(names) != 1 else ''}, +{plus} -{minus})"


def _rework_notes(run: Run) -> dict[str, list[str]]:
    """Per stage that was sent back to: '1 rework from verify'. Keys of run.loops are 'from->to' with an optional kind."""
    notes: dict[str, list[str]] = {}
    for key, count in run.loops.items():
        edge, _, kind = key.partition(":")
        src, _, dst = edge.partition("->")
        if not dst or kind == "question":
            continue
        what = {"conflict": f"{count} conflict rework from {src}", "human": f"{count} rework by you"}.get(kind, f"{count} rework from {src}")
        notes.setdefault(dst, []).append(what)
    return notes


def _stages(run: Run, approved_by: dict[str, str]) -> str:
    latest = {}
    for s in run.stages:
        latest[s.id] = s  # a later visit replaces an earlier one; the order stays that of first appearance
    rework = _rework_notes(run)
    parts = []
    for sid, s in latest.items():
        status = s.status.replace("_", " ")
        if s.status == "done" and sid in approved_by:
            status = f"approved by {approved_by[sid]}"
        extra = f" ({', '.join(rework[sid])})" if sid in rework else ""
        parts.append(f"{sid} {status}{extra}")
    return " · ".join(parts) or "No stages ran."


def _junit(run_dir: Path) -> tuple[int, int] | None:
    total = failed = 0
    found = False
    for path in sorted(run_dir.glob("tasks/*/work/*.junit.xml")):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        found = True
        for case in root.iter("testcase"):
            total += 1
            failed += case.find("failure") is not None or case.find("error") is not None
    return (total, failed) if found else None


def _evidence(run: Run, run_dir: Path) -> str:
    parts = []
    tests = _junit(run_dir)
    if tests:
        parts.append(f"Tests {tests[0] - tests[1]} passed, {tests[1]} failed")
    gates: dict[str, bool] = {}
    for e in read_events(run_dir):
        if e.type in ("gate_passed", "gate_failed"):
            gates[str(e.data.get("gate"))] = e.type == "gate_passed"
    if "scope-diff" in gates:
        parts.append(f"Scope check {'passed' if gates['scope-diff'] else 'failed'}")
    if gates:
        ok = sum(gates.values())
        parts.append(f"Gates {ok} passed, {len(gates) - ok} failed")
    if any(s.id.startswith("review") for s in run.stages):
        blocking, unreadable = findings_at_or_above(run, run_dir, "low")
        if unreadable:
            parts.append(f"Review findings: not readable ({unreadable})")
        else:
            parts.append(f"Review findings: {len(blocking)} read" + (f", first: {blocking[0]}" if blocking else ""))
    return " · ".join(parts) or "None recorded."


def _closes(run: Run) -> str | None:
    """`Closes #42` for a GitHub request, so merging the pull request closes the issue (module 13)."""
    if run.request.source.type != "github":
        return None
    number = run.request.source.ref.rsplit("#", 1)[-1]
    return f"Closes #{number}" if number.isdigit() else None


def _decisions_and_notes(run_dir: Path) -> str:
    lines = []
    for stage, visit, packet, dec in answered_decisions(run_dir):
        titles = {d.get("id"): d for d in packet.get("decisions") or []}
        for did, choice in (dec.get("choices") or {}).items():
            d = titles.get(did) or {}
            option = next((o.get("name", choice) for o in d.get("options") or [] if o.get("id") == choice), choice)
            lines.append(f"- {stage} (visit {visit}): {d.get('title', did)}: {option} (by {dec.get('by', 'unknown')})")
        if dec.get("notes"):
            lines.append(f"- {stage} note: {dec['notes']}")
    for path in sorted(run_dir.glob("tasks/*/notes.jsonl")):
        for line in read_jsonl(path):
            if line.get("state") == "queued":
                lines.append(f"- Note to {path.parent.name} by {line.get('by', 'unknown')}: {line.get('text', '')}")
    return "\n".join(lines) or "None"


def _command_attempts(run_dir: Path) -> int:
    """Finished attempts of tasks that run a command, not a model. They have no model name and no tokens, so
    `usage.summarize` files them under `unknown` (module 14); the summary names them for what they are."""
    from .usage import read_usage
    tasks = run_dir / "tasks"
    return sum(1 for tdir in (sorted(tasks.iterdir()) if tasks.is_dir() else []) for r in read_usage(run_dir, tdir.name)
               if r.exit != "started" and r.harness == "command" and not r.models)


def _usage(usage: UsageReport, commands: int = 0) -> str:
    lines = []
    for model, t in sorted(usage.by_model.items()):
        attempts = t.attempts
        if model == "unknown" and commands:
            attempts -= commands          # the command attempts have their own line below; none of them has a token count
            if attempts <= 0:
                continue
            t = ModelTotals(attempts, t.input_tokens, t.output_tokens, t.total_tokens, t.attempts_without_count - commands,
                            t.minutes)
        tokens = "tokens unknown" if t.attempts_without_count == t.attempts else f"{t.total_tokens:,} tokens"
        if 0 < t.attempts_without_count < t.attempts:
            tokens += f" ({t.attempts_without_count} without a count)"
        lines.append(f"{model}: {t.attempts} attempt{'s' if t.attempts != 1 else ''}, {tokens}, {t.minutes:.0f} min")
    if commands:
        lines.append(f"commands, no model: {commands} attempt{'s' if commands != 1 else ''}, no tokens to count")
    return "\n".join(lines) or "No attempts recorded."


def _merge(run_dir: Path) -> str:
    path = run_dir / "merge.json"
    if not path.is_file():
        return "Not evaluated."
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return "Not evaluated: merge.json could not be read."
    return "Auto-merge: every rule passed" if doc.get("auto") else f"Human review: {doc.get('reason', 'no reason recorded')}"


def render_summary(run_dir: Path, usage: UsageReport, base: str | None = None, *, delivering: bool = False) -> Path:
    """Write `summary.md` from the run's state and artifacts, and return its path. Rendering twice gives the same text.

    `base` is the repo's configured base branch. It is used for the file list until a pull request names its own base
    (item 37: before the pull request exists, a repo whose base is not main had no file list).

    `delivering` is set when the summary is written as the run delivers. The run is then about to wait for review, so
    the header says that instead of `running`, which is what run.json still holds until the pull request exists."""
    run = read_run(run_dir)
    approved_by = {stage: str(dec.get("by", "unknown")) for stage, _, _, dec in answered_decisions(run_dir)}
    head = f"Request: {run.request.source.ref} · Workflow: {run.workflow or 'none'} · Result: {'awaiting review' if delivering and run.status == 'running' else run.status}"
    if run.pr:
        head += f" · PR #{run.pr.number}"
    closes = _closes(run)
    title = f"# {run.run_id}: {run.request.title}\n{head}" + (f"\n{closes}" if closes else "")
    text = "\n\n".join([
        title,
        f"## What changed\n{_what_changed(run, base)}",
        f"## Stages\n{_stages(run, approved_by)}",
        f"## Evidence\n{_evidence(run, run_dir)}",
        f"## Decisions and notes\n{_decisions_and_notes(run_dir)}",
        f"## Usage\n{_usage(usage, _command_attempts(run_dir))}",
        f"## Merge\n{_merge(run_dir)}",
    ]) + "\n"
    path = run_dir / "summary.md"
    write_text_atomic(path, text)
    return path


# A finding of this severity or higher blocks auto-merge. The gate `no-blocking-findings` uses the same list.
SEVERITY_ORDER = ("low", "medium", "high")


def findings_at_or_above(run: Run, run_dir: Path, threshold: str) -> tuple[list[str], str | None]:
    """The findings of every review stage at or above `threshold`, as text, and a reason when any review artifact
    is missing or unreadable (None when every artifact passed the review-findings schema). A review task with no
    findings file, or one that fails the schema, makes the decision unknowable, so the caller blocks on it."""
    limit = SEVERITY_ORDER.index(threshold)
    blocking: list[str] = []
    for stage in (s for s in run.stages if s.id.startswith("review")):
        for task_id in stage.tasks:
            folder = run_dir / "tasks" / task_id
            artifacts = sorted(p for p in folder.glob("*.json")
                               if p.name not in ("task.json", "progress.json") and not p.name.startswith("ledger"))
            if not artifacts:
                return blocking, f"review task {task_id} wrote no findings file"
            for path in artifacts:
                try:
                    doc = json.loads(path.read_text())
                    validate(doc, "review-findings", file=str(path))
                except (OSError, ValueError, FactoryError) as e:
                    return blocking, f"{path.name} is not readable findings: {getattr(e, 'message', e)}"
                for f in doc["findings"]:
                    if SEVERITY_ORDER.index(f["severity"]) >= limit:
                        blocking.append(f"{f['severity']} {f['file']}:{f['line']} {f['rule']}")
    return blocking, None
