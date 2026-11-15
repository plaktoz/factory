"""Delivery (module 13): the pull request or sink, the merge policy, and watching the pull request.

Task branches join the run branch in module 7, never here. This module opens the run branch's pull request (or a doc
sink's), decides deterministically whether that pull request may auto-merge, and watches it until it is merged or closed.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

from .adapters.tracker.base import TrackerAdapter
from .atomic import read_jsonl, write_json_atomic, write_text_atomic
from .config import Config
from .errors import FactoryError
from .gitops import create_delivery_branch, git, push
from .prs import PullRequests
from .state import append_event, factory_home, read_events, read_run
from .summary import answered_decisions, diff_stats
from .types import PrRef, PrState, Run
from .validate import validate
from .yamlio import load_yaml

# Paths in the repo that a run's deliverables go to (module 7, 11, 13). They name the target repo's folders, not this
# factory repo's docs/.
ADR_DIR = "docs/adr"
RESEARCH_DIR = "docs/research"

# Files that change a dependency (module 13, never_auto_if.dependency_manifests_changed). Matched on the file name.
MANIFESTS = (
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
    "pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt", "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock",
    "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "settings.gradle.kts", "gradle.lockfile", "Gemfile", "Gemfile.lock", "composer.json", "composer.lock", "*.csproj",
    "packages.lock.json", "Directory.Packages.props", "mix.exs", "mix.lock", "pubspec.yaml", "pubspec.lock",
)

# Words in a merge error that mean branch protection or a required check refused the merge (module 13 errors).
PROTECTION_MARKERS = ("branch protection", "protected branch", "base branch policy", "not mergeable")

# Used when no merge-policy.yaml is in the run's kit: nothing is auto (fail closed).
_NO_POLICY = {
    "default": "human",
    "auto": {"workflows": [], "type_source": [], "require": {"gates": "all_passed", "ci": "green", "max_files": 1,
                                                             "max_lines": 1}},
    "never_auto_if": {},
}


@dataclass
class RuleResult:
    """One rule of the merge policy. `passed` means the rule allows auto-merge: for a never_auto_if rule, that it did
    not trigger. `detail` is the sentence the pull request and the dashboard show."""

    rule: str
    passed: bool
    detail: str


@dataclass
class MergeDecision:
    auto: bool
    rules: list[RuleResult]
    reason: str


@dataclass
class SinkResult:
    """What write_sink delivered: the sink's name, where it went (a pull request URL, an issue ref or a file path)."""

    sink: str
    target: str | None
    pr: PrRef | None = None


# --- pull request ---------------------------------------------------------------------------------------------------

def _summary_file(run_dir: Path) -> Path:
    path = run_dir / "summary.md"
    if not path.is_file():
        raise FactoryError("config.invalid", f"{path.name} is missing from {run_dir.name}",
                           hint="render the run summary before the sink runs")
    return path


def _base(cfg: Config) -> str:
    return (cfg.repo or {}).get("base_branch") or "main"


def _create(prs: PullRequests, run: Run, *, base: str, head: str, body: Path) -> PrRef:
    """A failed creation is transient (module 13 errors). A human-kind error, such as expired login, keeps its kind."""
    try:
        return prs.create(run.worktree, base=base, head=head, title=run.request.title, body_file=body, labels=[])
    except FactoryError as e:
        if e.kind == "human":
            raise
        raise FactoryError("git.network", f"the pull request was not created: {e.message}") from e


def open_pr(run_dir: Path, cfg: Config, prs: PullRequests) -> PrRef:
    """Push the run branch and open its pull request with summary.md as the body. Returns the existing one if opened."""
    run = read_run(run_dir)
    if run.pr is not None:
        return run.pr
    if run.branch is None:
        raise FactoryError("config.invalid", f"run {run.run_id} has no branch to open a pull request from",
                           hint="a read-only run gets its branch at delivery, through its doc sink")
    body = _summary_file(run_dir)
    push(run.worktree, run.branch)
    ref = _create(prs, run, base=_base(cfg), head=run.branch, body=body)
    append_event(run_dir, "pr_opened", pr=ref.number, url=ref.url)
    return ref


def _commit(worktree: Path, rel: str, message: str) -> None:
    """Stage one file and commit it, unless the file is already committed (a repeat changes nothing)."""
    git(worktree, "add", "--", rel)
    if git(worktree, "diff", "--cached", "--quiet", check=False).returncode != 0:
        git(worktree, "-c", "user.name=factory", "-c", "user.email=factory@local", "commit", "-m", message)


# --- ADR ------------------------------------------------------------------------------------------------------------

def write_adr(run_dir: Path, worktree: Path) -> Path | None:
    """docs/adr/<date>-<run id>.md from the approved architecture decision, committed so the pull request carries it.

    The name has the date and the run id, never a counter (module 7, 11). None when no architecture decision was approved.
    """
    approved = [a for a in answered_decisions(run_dir) if a[0] == "architecture"]
    if not approved:
        return None
    run = read_run(run_dir)
    _, _, packet, dec = approved[-1]
    day = str(dec.get("at") or "")[:10] or datetime.now().astimezone().date().isoformat()
    rel = f"{ADR_DIR}/{day}-{run.run_id}.md"
    path = worktree / rel
    write_text_atomic(path, _adr_text(run, day, packet, dec))
    _commit(worktree, rel, f"docs: ADR for {run.run_id}")
    return path


def _adr_text(run: Run, day: str, packet: dict, dec: dict) -> str:
    lines = [f"# {run.request.title}", "", f"Run {run.run_id} on {day}, request {run.request.source.ref}", ""]
    choices = dec.get("choices") or {}
    for d in packet.get("decisions") or []:
        options = d.get("options") or []
        chosen = choices.get(d["id"], "")
        name = next((o.get("name", o["id"]) for o in options if o["id"] == chosen), chosen)
        lines += [f"## {d.get('title', d['id'])}", "", f"Chosen: {name}", "", f"Why: {d.get('why', '')}", "",
                  "Options considered: " + ", ".join(o.get("name", o["id"]) for o in options), ""]
    if dec.get("notes"):
        lines += ["## Notes", "", str(dec["notes"]), ""]
    return "\n".join(lines)


# --- merge policy -----------------------------------------------------------------------------------------------------

def _policy(run: Run) -> dict:
    """merge-policy.yaml from the run's kit snapshot, so an edit in the main checkout cannot change a running run.

    Module 3's load_config does not read this file yet, so module 13 reads it here and checks it against its schema."""
    path = factory_home() / "kits" / run.kit_hash / ".factory" / "config" / "merge-policy.yaml"
    if not path.is_file():
        return _NO_POLICY
    doc = load_yaml(path.read_text(), file=str(path))
    validate(doc, "merge-policy", file=str(path))
    return doc


def _glob(pattern: str, path: str) -> bool:
    """A repo glob where `**/` matches zero or more folders, so `**/migrations/**` also matches `migrations/0001.sql`."""
    regex, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex, i = regex + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            regex, i = regex + ".*", i + 2
        elif pattern[i] == "*":
            regex, i = regex + "[^/]*", i + 1
        elif pattern[i] == "?":
            regex, i = regex + "[^/]", i + 1
        else:
            regex, i = regex + re.escape(pattern[i]), i + 1
    return re.fullmatch(regex, path) is not None


def _is_manifest(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch(name, pattern) for pattern in MANIFESTS)


def _architecture_approved(run_dir: Path) -> bool:
    return any(a[0] == "architecture" for a in answered_decisions(run_dir))


def _steered(run_dir: Path) -> bool:
    """A human steered the run: a steering note was queued for a task, or an approved decision carried notes."""
    queued = any(line.get("state") == "queued" for path in run_dir.glob("tasks/*/notes.jsonl")
                 for line in read_jsonl(path))
    return queued or any(dec.get("notes") for _, _, _, dec in answered_decisions(run_dir))


def _rework_loops(run: Run) -> int:
    """Rework loops used. Question loops (a stage waiting on an answer) are not rework."""
    return sum(n for key, n in run.loops.items() if not key.endswith(":question"))


def _gate_rule(run: Run, run_dir: Path) -> RuleResult:
    name = "auto.require.gates"
    skipped = [s.id for s in run.stages if s.status == "skipped"]
    if skipped:
        return RuleResult(name, False, f"gates skipped in {', '.join(skipped)}")
    last: dict[str, bool] = {}
    for e in read_events(run_dir):
        if e.type in ("gate_passed", "gate_failed"):
            last[str(e.data.get("gate"))] = e.type == "gate_passed"  # the latest result of a gate wins
    if not last:
        return RuleResult(name, False, "no gate results recorded")
    failed = [g for g, ok in last.items() if not ok]
    if failed:
        return RuleResult(name, False, f"gates failed: {', '.join(failed)}")
    return RuleResult(name, True, f"all {len(last)} gates passed")


def _never_rules(never: dict, run: Run, run_dir: Path, changed: list[str]) -> list[RuleResult]:
    """One result per never_auto_if key that is set. A key that is off (false) names no rule and is left out."""
    out: list[RuleResult] = []
    if never.get("paths"):
        hits = [f"{f} (matches {p})" for f in changed for p in never["paths"] if _glob(p, f)]
        out.append(RuleResult("never_auto_if.paths", not hits,
                              "touched " + "; ".join(hits) if hits else "no protected path touched"))
    if never.get("dependency_manifests_changed"):
        hits = [f for f in changed if _is_manifest(f)]
        out.append(RuleResult("never_auto_if.dependency_manifests_changed", not hits,
                              "changed " + ", ".join(hits) if hits else "no dependency manifest changed"))
    if never.get("architecture_decision") and _architecture_approved(run_dir):
        out.append(RuleResult("never_auto_if.architecture_decision", False, "an architecture decision was approved"))
    elif never.get("architecture_decision"):
        out.append(RuleResult("never_auto_if.architecture_decision", True, "no architecture decision"))
    if never.get("review_findings_at_or_above"):
        # The review-findings schema is not written yet, so findings cannot be read. A run with a review stage needs a human.
        review = any(s.id.startswith("review") for s in run.stages)
        out.append(RuleResult("never_auto_if.review_findings_at_or_above", not review,
                              "review findings cannot be read yet (no review-findings schema)" if review
                              else "no review stage, so no findings"))
    if never.get("notes_used"):
        steered = _steered(run_dir)
        out.append(RuleResult("never_auto_if.notes_used", not steered,
                              "a human steered the run with notes" if steered else "no notes used"))
    if never.get("rework_loops_used_at_least") is not None:
        limit, used = never["rework_loops_used_at_least"], _rework_loops(run)
        out.append(RuleResult("never_auto_if.rework_loops_used_at_least", used < limit,
                              f"{used} rework loops used, at least {limit}" if used >= limit
                              else f"{used} rework loops used, under {limit}"))
    return out


def evaluate_merge(run_dir: Path, cfg: Config, *, changed: list[str], ci: str) -> MergeDecision:
    """Every rule with its result; auto only when all pass. Writes merge.json and the merge_evaluated event.

    Phase 1 reads the policy from the run's kit snapshot and counts lines from the run branch against the base. A rule
    that cannot be read fails, so the pull request goes to a human.
    """
    run = read_run(run_dir)
    policy = _policy(run)
    auto, never = policy["auto"], policy.get("never_auto_if") or {}
    req = auto["require"]
    stats = diff_stats(run.worktree, _base(cfg))

    rules: list[RuleResult] = []
    in_workflows = run.workflow in auto["workflows"]
    rules.append(RuleResult("auto.workflows", in_workflows,
                            f"{run.workflow} is in the auto workflows" if in_workflows
                            else f"{run.workflow} is not in the auto workflows"))
    source = run.request.type_source
    rules.append(RuleResult("auto.type_source", source in auto["type_source"],
                            f"type set from {source}" if source in auto["type_source"]
                            else f"type came from {source or 'no source'}, which is not an auto type source"))
    rules.append(_gate_rule(run, run_dir))
    rules.append(RuleResult("auto.require.ci", ci == req["ci"], f"CI is {ci}"))
    rules.append(RuleResult("auto.require.max_files", len(changed) <= req["max_files"],
                            f"{len(changed)} files changed (max {req['max_files']})"))
    if stats is None:
        rules.append(RuleResult("auto.require.max_lines", False, "the changed lines could not be counted"))
    else:
        lines = sum(a + d for _, a, d in stats)
        rules.append(RuleResult("auto.require.max_lines", lines <= req["max_lines"],
                                f"{lines} lines changed (max {req['max_lines']})"))
    rules += _never_rules(never, run, run_dir, changed)

    allowed = all(r.passed for r in rules)
    reason = "every rule passed" if allowed else "; ".join(r.detail for r in rules if not r.passed)
    write_json_atomic(run_dir / "merge.json", {"auto": allowed, "reason": reason,
                                               "rules": [asdict(r) for r in rules]})
    append_event(run_dir, "merge_evaluated", auto=allowed, reason=reason)
    return MergeDecision(auto=allowed, rules=rules, reason=reason)


def merge_or_request_review(pr: PrRef, decision: MergeDecision, prs: PullRequests,
                            reviewers: list[str]) -> None:
    """Auto: ask GitHub to squash-merge when the checks pass (branch protection still applies). Human: request reviewers.

    A merge that branch protection refuses is a human error (delivery.merge_blocked), not a retry.
    """
    if not decision.auto:
        prs.request_reviewers(pr, reviewers)
        return
    try:
        prs.merge(pr, method="squash", auto=True, delete_branch=True)
    except FactoryError as e:
        if any(marker in e.message.lower() for marker in PROTECTION_MARKERS):
            raise FactoryError("delivery.merge_blocked", e.message) from e
        raise


def watch_pr(run_dir: Path, prs: PullRequests) -> PrState:
    """The pull request's state, CI and checks output. Writes `merged` once, when the pull request is seen merged."""
    run = read_run(run_dir)
    if run.pr is None:
        raise FactoryError("config.invalid", f"run {run.run_id} has no pull request to watch",
                           hint="open the pull request first")
    state = prs.state(run.pr)
    if state.state == "merged" and not any(e.type == "merged" for e in read_events(run_dir)):
        append_event(run_dir, "merged", pr=run.pr.number)
    return state


# --- sinks ----------------------------------------------------------------------------------------------------------

def _sink_of(run: Run) -> str:
    """The workflow's sink, read from its file in the run's kit snapshot (module 5 defaults: pull_request when the
    workflow writes, comment when it does not)."""
    if not run.workflow:
        raise FactoryError("config.invalid", f"run {run.run_id} has no workflow", hint="a run needs a workflow before it delivers")
    kit = factory_home() / "kits" / run.kit_hash
    for path in (kit / ".factory" / "config" / "workflows" / f"{run.workflow}.yaml",
                 kit / "factory" / "workflows" / f"{run.workflow}.yaml"):
        if path.is_file():
            doc = load_yaml(path.read_text(), file=str(path)) or {}
            if "sink" in doc:
                return str(doc["sink"])
            return "pull_request" if (doc.get("policy") or {}).get("write", False) else "comment"
    raise FactoryError("config.invalid", f"no workflow file named {run.workflow!r} in the run's kit",
                       hint=f"add {run.workflow}.yaml to the kit's workflows")


def _doc_pr(run_dir: Path, run: Run, cfg: Config, prs: PullRequests, body: Path) -> PrRef:
    """Doc sink: the report goes to docs/research/<run id>.md on the run's branch, which is created only now."""
    if run.pr is not None:
        return run.pr
    reports = sorted(run_dir.glob("tasks/*/work/report.md"))
    if not reports:
        raise FactoryError("config.invalid", f"run {run.run_id} wrote no report.md",
                           hint="the task that writes the report must name report.md as its out")
    rel = f"{RESEARCH_DIR}/{run.run_id}.md"
    write_text_atomic(run.worktree / rel, reports[0].read_text())
    if git(run.worktree, "symbolic-ref", "--quiet", "HEAD", check=False).returncode != 0:  # still detached
        create_delivery_branch(run.worktree, run.run_id)
    _commit(run.worktree, rel, f"docs: research report for {run.run_id}")
    push(run.worktree, run.run_id)
    ref = _create(prs, run, base=_base(cfg), head=run.run_id, body=body)
    append_event(run_dir, "pr_opened", pr=ref.number, url=ref.url)
    return ref


def _comment(run: Run, tracker: TrackerAdapter, body: str) -> str:
    """Comment sink: the source issue gets the summary; a markdown request gets it appended to its file."""
    src = run.request.source
    if src.type == "markdown" and src.files:
        path = Path(src.files[0])
        write_text_atomic(path, path.read_text().rstrip() + "\n\n## Answer\n\n" + body + "\n")
        return str(path)
    tracker.set_status(src.ref, "factory:done", comment=body)  # delivery runs when the run has finished its work
    return src.ref


def write_sink(run_dir: Path, cfg: Config, *, tracker: TrackerAdapter, prs: PullRequests) -> SinkResult:
    """Deliver through the run's sink: pull_request, doc or comment (module 13 sinks table). Writes sink_written."""
    run = read_run(run_dir)
    sink = _sink_of(run)
    body = _summary_file(run_dir)
    if sink == "pull_request":
        pr = open_pr(run_dir, cfg, prs)
        target = pr.url
    elif sink == "doc":
        pr = _doc_pr(run_dir, run, cfg, prs, body)
        target = pr.url
    elif sink == "comment":
        pr, target = None, _comment(run, tracker, body.read_text())
    else:
        raise FactoryError("config.invalid", f"sink {sink!r} is not one of pull_request, doc, comment",
                           hint="set sink to one of those in the workflow file")
    append_event(run_dir, "sink_written", sink=sink, target=target)
    return SinkResult(sink=sink, target=target, pr=pr)
