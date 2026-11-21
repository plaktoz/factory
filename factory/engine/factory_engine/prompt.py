"""Prompt assembly and the helpers-ledger gate (module 9).

build_prompt is a fixed template filled by code. It contains the skill reference, a request summary, scope and deny
paths, the helper policy in plain words, feedback records, delivered notes, progress.md and the output schema. Practice
packs appear as paths with a one-line description, never their full text.
"""

from __future__ import annotations

from .adapters.worker.base import TaskContext
from .atomic import read_jsonl
from .gitops import changed_files
from .skills import SkillRef, _front_matter
from .types import GateContext, GateResult, GateSpec, HelperPolicy

LEDGER = "helpers.jsonl"
PROGRESS = "progress.md"


def helper_policy_words(policy: HelperPolicy) -> str:
    """The helper policy in plain words. The ledger is asked for in every mode: the gate needs it whenever files change."""
    if policy.mode == "off" or policy.max <= 0:
        return (f"Helpers are off. Do not start helpers or subagents. Do all of the work yourself. Create "
                f"$FACTORY_TASK_DIR/{LEDGER} empty.")
    ledger = f"Append one JSON line to $FACTORY_TASK_DIR/{LEDGER} for every helper you start, with the keys " \
             '"name", "purpose" and "started". Create the file even when you start no helpers.'
    lines = [
        f"You may start at most {policy.max} helper{'s' if policy.max != 1 else ''} (subagents) for this task. "
        "Start none if the work is small.",
        ledger,
    ]
    if policy.split_hints:
        lines.append("Suggested ways to split the work: " + ", ".join(policy.split_hints) + ".")
    lines.append(f"At each milestone, write a short note of where you are to $FACTORY_TASK_DIR/{PROGRESS}, so a restart "
                 "can resume instead of starting over.")
    if policy.timeout_minutes:
        lines.append(f"Each helper must finish within {policy.timeout_minutes} minutes.")
    return "\n".join(lines)


def _skill_line(skill: SkillRef) -> str:
    return f"{skill.name} (installed in the worktree as .claude/skills/factory-{skill.name}, source: {skill.source})"


def _pack_line(pack: SkillRef) -> str:
    """A practice pack is named by its path and one line; its text is never put in the prompt."""
    md = pack.path / "SKILL.md"
    desc = str(_front_matter(md).get("description") or "").strip() if md.is_file() else ""
    return f"- {md}: {desc.splitlines()[0] if desc else pack.name}"


def _section(title: str, body: str) -> str:
    return f"## {title}\n{body.rstrip()}\n"


def build_prompt(ctx: TaskContext) -> str:
    """Fixed template, no LLM. The same context always gives the same text."""
    rq = ctx.request
    out: list[str] = [f"You are a worker in an automated software factory. Task {ctx.task_id}, stage {ctx.stage}, "
                      f"attempt {ctx.attempt}. You run headless: nobody can answer a question.\n"]
    if ctx.skill is not None:
        out.append(_section("Skill", f"Follow this skill: {_skill_line(ctx.skill)}. Read its SKILL.md first."))
    summary = [f"Title: {rq.title}", f"Type: {rq.type or 'unknown'}", f"Priority: {rq.priority or 'none'}"]
    if rq.acceptance:
        summary.append("Acceptance:\n" + "\n".join(f"- {a}" for a in rq.acceptance))
    summary.append(f"Body:\n{rq.source.body}")
    out.append(_section("Request", "\n".join(summary)))
    if ctx.question:
        out.append(_section("Your question", "Answer this question for the request above. Answer only this one.\n\n" + ctx.question))
    out.append(_section("Scope", "You may change only these paths:\n" + ("\n".join(f"- {p}" for p in ctx.scope) or "- (none)")
                        + "\nYou must never change these paths:\n" + ("\n".join(f"- {p}" for p in ctx.deny) or "- (none)")
                        + "\nYour working folder is the task worktree. Never commit, push or touch git history."))
    out.append(_section("Helpers", helper_policy_words(ctx.helpers)))
    if ctx.practices:
        out.append(_section("Practice packs", "Read the ones that apply to your work:\n" + "\n".join(_pack_line(p) for p in ctx.practices)))
    if ctx.feedback:
        recs = [f"### {p.name}\n{p.read_text().rstrip()}" for p in ctx.feedback if p.is_file()]
        out.append(_section("Feedback from earlier attempts (newest last)", "\n\n".join(recs) or "(none readable)"))
    if ctx.notes:
        out.append(_section("Notes from the operator", "\n".join(f"- {n}" for n in ctx.notes)))
    if ctx.progress is not None and ctx.progress.is_file():
        out.append(_section("Progress so far (you are resuming)", ctx.progress.read_text()))
    schema = f"Its schema is {ctx.output_schema}." if ctx.output_schema else "It has no fixed schema."
    out.append(_section("Output", f"Write exactly one artifact to $FACTORY_TASK_DIR/{ctx.artifact_name}. {schema} "
                        f"Write nothing else there except {PROGRESS} and {LEDGER}."))
    return "\n".join(out)


def check_helpers_ledger(spec: GateSpec, ctx: GateContext) -> GateResult:
    """The helpers-ledger gate (used by module 8). spec.args carries the task's helper policy: {"mode": ..., "max": ...}.

    Fails when files changed and the ledger is missing, or when the ledger lists more helpers than the maximum. With
    helpers off the maximum is 0 and the worker writes an empty ledger. The evidence has the same keys either way."""
    args = spec.args or {}
    mode = args.get("mode", "off")
    maximum = 0 if mode == "off" else int(args.get("max", 0))
    ledger = (ctx.task_dir / LEDGER) if ctx.task_dir is not None else None
    files = changed_files(ctx.worktree, ctx.task_base) if ctx.task_base else []
    entries = read_jsonl(ledger) if ledger is not None and ledger.is_file() else []
    details = {"mode": mode, "max": maximum, "helpers": len(entries), "files": files, "ledger": str(ledger) if ledger else None}
    if files and (ledger is None or not ledger.is_file()):
        return GateResult(False, "helpers-ledger", "gate.ledger_missing",
                          f"{len(files)} files changed and {LEDGER} is missing", details)
    if len(entries) > maximum:
        return GateResult(False, "helpers-ledger", "gate.ledger_over_max",
                          f"the ledger lists {len(entries)} helpers; the maximum is {maximum}", details)
    return GateResult(True, "helpers-ledger", "ok", "", details)


