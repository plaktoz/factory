"""Error handling and rework (module 8): sort each failure into one handling type, retry infrastructure calls with
backoff, write feedback records, and route a run back to an earlier stage within a loop budget kept in run.json.

route() and its helpers change the Run in memory and return a Routing. The engine that holds the run's lock writes
run.json (module 6A), so the loop counters and the retrying state survive a restart.
"""

from __future__ import annotations

import json

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeVar

from .adapters.worker.base import AttemptResult
from .atomic import write_json_atomic
from .clock import SystemClock
from .errors import ErrorKind, FactoryError
from .state import append_event, task_dir
from .types import AttentionItem, Clock, GateResult, InfraWait, JoinResult, Run, Stage, StageState, Workflow
from .validate import validate

if TYPE_CHECKING:
    from .decisions import Outcome  # module 11; imported for the annotation only

T = TypeVar("T")
# Waits between the three tries of an infrastructure call (module 8: "3 tries"). The spec also lists a 2 min delay;
# three tries have two gaps, so it has no slot here and is left for the coordinator to place.
DEFAULT_DELAYS: tuple[int, ...] = (5, 30)
SCHEMA_VERSION = 1

# A hook that fails for one of these reasons failed outside the change, so it is transient, not rework.
_HOOK_TRANSIENT = re.compile(
    r"could not resolve host|temporary failure in name resolution|network is unreachable|"
    r"connection (?:refused|reset|timed out)|operation timed out|command not found|"
    r"executable file not found|rate limit",
    re.IGNORECASE,
)

# A worker's own error code maps to one handling type. A rate limit waits; a crash is a task retry; the rest need a person.
_WORKER_ERROR_KIND: dict[str, ErrorKind] = {
    "rate_limit": "transient",
    "crash": "task_retry",
    "auth": "human",
    "binary_missing": "human",
    "model_not_found": "human",
}

# Gate codes that mean the artifact was bad, which the class table lists as a worker error.
_ARTIFACT_GATE_CODES = frozenset({"gate.schema", "gate.no_artifact"})


@dataclass
class Routing:
    """What the engine does next. `reset` lists the stages sent back to pending, in workflow order.

    `loop` and `max` are the edge's count after this routing and its limit. `max` is 0 when the edge has no limit."""

    action: Literal["retry_task", "goto", "wait", "blocked", "aborted"]
    goto: str | None = None
    reset: list[str] = field(default_factory=list)
    loop: int = 0
    max: int = 0
    reason: str = ""
    code: str | None = None  # the error code of a block the engine raised itself, such as gate.no_test_results


def _hook_kind(output: str) -> ErrorKind:
    return "transient" if _HOOK_TRANSIENT.search(output) else "rework"


def classify(failure: FactoryError | AttemptResult | GateResult | JoinResult) -> ErrorKind:
    """One handling type for each failure (section 19). A result that did not fail is a programming error.

    A failed join is "rework" here, because ErrorKind has no conflict value. A caller that sees conflict_files must
    route with route_conflict, which follows on_conflict. A join with hook_failed carries the hook's output in
    JoinResult.hook_output, so it is read like any other hook output: a network or missing-tool error is transient and
    anything else is rework. A hook's output also arrives in a git.hook_failed FactoryError or in a GateResult with code
    gate.hook_failed."""
    if isinstance(failure, FactoryError):
        if failure.code == "git.hook_failed":
            return _hook_kind(failure.message)
        return failure.kind
    if isinstance(failure, AttemptResult):
        if failure.exit == "ok":
            if failure.artifact is not None:
                raise ValueError("an attempt that finished with an artifact did not fail")
            return "task_retry"  # no artifact: a worker error, retried from the checkpoint
        if failure.error_kind is not None:
            return _WORKER_ERROR_KIND[failure.error_kind]
        return "task_retry"  # non-zero exit, timeout or kill: a worker error (class table)
    if isinstance(failure, GateResult):
        if failure.passed:
            raise ValueError("a gate that passed did not fail")
        if failure.code in _ARTIFACT_GATE_CODES:
            return "task_retry"
        if failure.code == "gate.hook_failed":
            # A caller wraps a hook's git.hook_failed in a GateResult, so its output is here to classify.
            return _hook_kind(failure.output_tail)
        return "rework"
    if failure.ok:
        raise ValueError("a join that succeeded did not fail")
    if failure.hook_failed and failure.hook_output:
        return _hook_kind(failure.hook_output)
    return "rework"


def hook_failure_result(error: FactoryError) -> GateResult:
    """Wrap a git.hook_failed error as a GateResult, so the hook's output reaches classify and build_feedback."""
    if error.code != "git.hook_failed":
        raise ValueError(f"{error.code} is not a hook failure")
    return GateResult(passed=False, gate="repo hook", code="gate.hook_failed", output_tail=error.message,
                      details={"exit_code": None})


def with_backoff(fn: Callable[[], T], *, delays: tuple[int, ...] = DEFAULT_DELAYS, clock: Clock) -> T:
    """Make len(delays) + 1 tries of fn, and wait for each delay before the try that follows it.

    A try fails when it raises a transient FactoryError, or when it returns a rate-limited AttemptResult. Any other
    error raises at once and is not retried here. With the default delays that is three tries, waiting 5 s then 30 s
    between them. When every try fails, the last failure is raised, or returned as an AttemptResult, for the caller
    to classify. The worker never sees these retries, and they use no task retry."""
    failure: FactoryError | AttemptResult | None = None
    for attempt in range(len(delays) + 1):
        try:
            result = fn()
        except FactoryError as e:
            if e.kind != "transient":
                raise
            failure = e
        else:
            limited = isinstance(result, AttemptResult) and result.exit != "ok" and result.error_kind == "rate_limit"
            if not limited:
                return result
            failure = result
        if attempt < len(delays):
            clock.sleep(delays[attempt])
    if isinstance(failure, FactoryError):
        raise failure
    assert failure is not None
    return failure  # type: ignore[return-value]


def _iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def build_feedback(run_dir: Path, *, from_stage: str, to_stage: str, result: GateResult | JoinResult,
                   loop: int, max_loops: int, task_ids: list[str]) -> Path:
    """Write one feedback record into each task folder of the stage the run goes back to, and log routed_back.

    Every field comes from the command's output: the exit code, the failing tests the gate read from JUnit XML, and
    the files git reports. `max_loops` of 0 means the edge has no limit, and the record then shows the loop number.
    Returns the first record written."""
    if isinstance(result, JoinResult):
        gate, exit_code, failed = "join", None, []
        files = list(result.conflict_files)
        if files:
            output = "merge conflict in:\n" + "\n".join(files)
        else:
            output = result.hook_output or "a repo hook failed on the join commit"
    else:
        gate, output = result.gate, result.output_tail
        exit_code = result.details.get("exit_code")
        failed = list(result.details.get("failed_tests", []))
        files = list(result.details.get("changed_files", []))
    doc = {"schema_version": SCHEMA_VERSION, "from_stage": from_stage, "to_stage": to_stage, "loop": loop,
           "max": max_loops or loop, "gate": gate, "exit_code": exit_code, "failed_tests": failed,
           "output_tail": output, "changed_files": files, "at": _iso(SystemClock().now())}
    return _write_records(run_dir, doc, task_ids, max_loops=max_loops)


def build_human_feedback(run_dir: Path, *, from_stage: str, to_stage: str, notes: str, loop: int, max_loops: int,
                         task_ids: list[str]) -> Path:
    """Write the notes of a human rework as a feedback record into each task folder of the stage the run goes back to.

    A human rework has no gate, exit code or test, so those fields hold the values the schema allows for none:
    gate "human", exit_code null and empty lists. `notes` is the operator's answer, and it is written even when empty,
    so the worker still sees that a person sent the stage back. Logs routed_back, as a gate rework does."""
    doc = {"schema_version": SCHEMA_VERSION, "from_stage": from_stage, "to_stage": to_stage, "loop": loop,
           "max": max_loops or loop, "gate": "human", "exit_code": None, "failed_tests": [], "output_tail": "",
           "changed_files": [], "at": _iso(SystemClock().now()), "notes": notes}
    return _write_records(run_dir, doc, task_ids, max_loops=max_loops)


def _write_records(run_dir: Path, doc: dict, task_ids: list[str], *, max_loops: int) -> Path:
    """Validate one feedback record, write it into each task folder, and log routed_back with the edge's limit as
    routed (0 when the edge has none). Returns the first record."""
    if not task_ids:
        raise ValueError("feedback needs at least one task folder to write into")
    from_stage, to_stage = doc["from_stage"], doc["to_stage"]
    validate(doc, "feedback", file=f"feedback {from_stage}->{to_stage}")
    first: Path | None = None
    for task_id in task_ids:
        folder = task_dir(run_dir, task_id) / "feedback"
        folder.mkdir(exist_ok=True)
        # A retry after a partial write skips a task that already holds this route's record, so no record is written
        # twice (owner decision, 2026-11-24: a failed write is retried on the next tick).
        same_route = [p for p in sorted(folder.glob(f"*-{from_stage}-to-{to_stage}.json"))
                      if json.loads(p.read_text()).get("loop") == doc["loop"]]
        if same_route:
            first = first or same_route[0]
            continue
        n = len(list(folder.glob("*.json"))) + 1
        path = folder / f"{n:03d}-{from_stage}-to-{to_stage}.json"
        write_json_atomic(path, doc)
        first = first or path
    append_event(run_dir, "routed_back", from_stage=from_stage, to_stage=to_stage, loop=doc["loop"],
                 max=max_loops, gate=doc["gate"], tasks=task_ids)
    assert first is not None
    return first


def _reset_from(run: Run, wf: Workflow, goto: str) -> list[str]:
    """Reset goto and every later stage to pending. A stage that had started gets a new visit. Earlier stages stay done."""
    order = [s.id for s in wf.stages]
    later = order[order.index(goto):]
    known = {st.id: st for st in run.stages}
    for sid in later:
        if sid not in known:
            st = StageState(id=sid, visit=1, status="pending", tasks=[], started=None, ended=None)
            run.stages.append(st)
            known[sid] = st
        st = known[sid]
        if st.status != "pending":
            st.visit += 1
        st.status, st.tasks, st.started, st.ended = "pending", [], None, None
    return later


def _check_target(wf: Workflow, stage: Stage, goto: str) -> None:
    order = [s.id for s in wf.stages]
    if goto not in order:
        raise FactoryError("config.invalid", f"stage {stage.id!r} routes to {goto!r}, which is not a stage of {wf.name}",
                           hint="name a stage of this workflow in on_fail, on_conflict or on_reject")
    if order.index(goto) > order.index(stage.id):
        raise FactoryError("config.invalid", f"stage {stage.id!r} routes forward to {goto!r}",
                           hint="a rework edge goes back to this stage or an earlier one")


def _blocked(run: Run, stage_id: str, summary: str, when: datetime) -> Routing:
    run.status = "blocked"
    run.attention = AttentionItem(kind="blocked", run_id=run.run_id, stage=stage_id, since=_iso(when),
                                  summary=summary, page=None, command=f"factory retry {run.run_id}")
    return Routing("blocked", reason=summary)


def block(run: Run, stage_id: str, reason: str, when: datetime, *, code: str, command: str) -> Routing:
    """Block the run for a person with this reason (module 8). The engine uses it when a stage's own check fails in a way
    no loop can fix, such as a verify stage with no test results (T1). `command` is the one the blocked card offers."""
    routing = _blocked(run, stage_id, reason, when)
    run.attention.command = command
    routing.code = code
    return routing


def _go(run: Run, wf: Workflow, stage: Stage, goto: str, *, key: str, limit: int | None, why: str) -> Routing:
    """Take one loop on an edge, or block the run when the loop reaches the edge's limit. None is unlimited.

    `limit` is the number of loops the edge allows. max 3 routes the first, second and third failure
    ("loop 1 of 3" to "loop 3 of 3") and blocks the fourth. The counter is kept in run.loops, so it survives a restart."""
    _check_target(wf, stage, goto)
    loop = run.loops.get(key, 0) + 1
    if limit is not None and loop > limit:
        return _blocked(run, stage.id, f"{why}: {key} reached its limit of {limit} loops", SystemClock().now())
    run.loops[key] = loop
    reset = _reset_from(run, wf, goto)
    run.stage, run.status, run.attention = goto, "running", None
    return Routing("goto", goto=goto, reset=reset, loop=loop, max=limit or 0, reason=why)


def route(run: Run, wf: Workflow, stage: Stage, failure: ErrorKind | Outcome) -> Routing:
    """Decide what happens next and change the run in memory.

    task_retry: retry the task. transient: the caller has already retried with with_backoff, and it calls
    start_infra_wait to put the run in retrying. rework: follow the stage's on_fail edge. human: the run is blocked
    for a person. A human answer (an Outcome) is routed by its status. A merge conflict goes to route_conflict."""
    if not isinstance(failure, str):
        return _route_outcome(run, wf, stage, failure)
    if failure == "fail_fast":
        raise ValueError("a fail_fast error stops before any work and is not routed; the CLI exits 2")
    if failure == "task_retry":
        return Routing("retry_task", reason="worker error: retry the task from its checkpoint")
    if failure == "transient":
        return Routing("wait", reason="infrastructure error: caller backs off, then starts the infra wait")
    if failure == "rework":
        if stage.on_fail is None:
            return _blocked(run, stage.id, f"{stage.id} failed and has no on_fail edge", SystemClock().now())
        edge = stage.on_fail
        return _go(run, wf, stage, edge.goto, key=f"{stage.id}->{edge.goto}", limit=edge.max,
                   why=f"{stage.id} failed its gate")
    if failure == "human":
        return _blocked(run, stage.id, f"{stage.id} needs a person", SystemClock().now())
    raise ValueError(f"unknown failure kind {failure!r}")


def may_retry(failed_attempt: int, retries: int) -> bool:
    """A failed task may run again while its failed attempt number is at most `retries` (module 8: retries per task).

    With the default retries of 2, attempts 1 and 2 may be followed by another attempt, and attempt 3 ends the task."""
    return failed_attempt <= retries


def route_conflict(run: Run, wf: Workflow, stage: Stage) -> Routing:
    """A merge conflict at join follows on_conflict, with its own loop count."""
    edge = stage.on_conflict
    if edge is None:
        return _blocked(run, stage.id, f"{stage.id} had a merge conflict and has no on_conflict edge", SystemClock().now())
    return _go(run, wf, stage, edge.goto, key=f"{stage.id}->{edge.goto}:conflict", limit=edge.max,
               why=f"{stage.id} had a merge conflict at join")


def route_red_ci(run: Run, wf: Workflow, stage: Stage) -> Routing:
    """Red CI on the open pull request follows the last stage's on_fail edge, with its own loop count (module 13)."""
    edge = stage.on_fail
    if edge is None:
        return _blocked(run, stage.id, f"CI is red on the pull request and {stage.id} has no on_fail edge",
                        SystemClock().now())
    return _go(run, wf, stage, edge.goto, key=f"{stage.id}->{edge.goto}:ci", limit=edge.max,
               why="CI is red on the pull request")


def _route_outcome(run: Run, wf: Workflow, stage: Stage, outcome: Outcome) -> Routing:
    """A human answer. Rework goes to on_reject with no limit, a question goes back to this stage, and reject aborts."""
    if outcome.status == "reject":
        run.status, run.attention = "aborted", None
        return Routing("aborted", reason="rejected by a person")
    if outcome.status == "question":
        return _go(run, wf, stage, stage.id, key=f"{stage.id}->{stage.id}:question", limit=None,
                   why=f"{stage.id} has questions for the packet task")
    if outcome.status == "rework":
        if stage.on_reject is None:
            return _blocked(run, stage.id, f"{stage.id} was sent back, but no on_reject stage is set", SystemClock().now())
        goto = stage.on_reject
        return _go(run, wf, stage, goto, key=f"{stage.id}->{goto}:human", limit=None,
                   why=f"{stage.id} sent back by a person")
    raise ValueError(f"a {outcome.status!r} answer does not route the run")


def start_infra_wait(run: Run, *, operation: str, error: FactoryError, clock: Clock,
                     tries: int = len(DEFAULT_DELAYS) + 1) -> None:
    """After with_backoff gives up, the run is retrying, with the operation and the start time in run.json.

    `tries` counts the tries made so far, so the default is the three of with_backoff."""
    run.infra_wait = InfraWait(since=_iso(clock.now()), tries=tries, last_error=f"{operation}: {error.message}")
    run.status = "retrying"


def infra_tick(run: Run, *, operation: str, error: FactoryError, clock: Clock, wait_hours: float) -> Routing:
    """One tick of a retrying run found the operation still failing. The run stays retrying until wait_hours have
    passed since the wait began, then it is blocked with an attention item. Call infra_recovered when it succeeds."""
    if run.infra_wait is None:
        raise ValueError("infra_tick needs a run that is waiting; call start_infra_wait first")
    now = clock.now()
    run.infra_wait.tries += 1
    run.infra_wait.last_error = f"{operation}: {error.message}"
    if now - datetime.fromisoformat(run.infra_wait.since) >= timedelta(hours=wait_hours):
        return _blocked(run, run.stage or "", f"{operation} has failed for {wait_hours:g} hours: {error.message}", now)
    return Routing("wait", reason=run.infra_wait.last_error)


def infra_recovered(run: Run) -> None:
    """The operation worked on a tick: the wait is cleared and the run goes on."""
    run.infra_wait = None
    if run.status == "retrying":
        run.status = "running"


def record_blocked(run_dir: Path, run: Run, routing: Routing) -> None:
    """Log run_blocked once for a run that route or infra_tick just blocked."""
    if routing.action != "blocked":
        raise ValueError("record_blocked takes the routing of a blocked run")
    append_event(run_dir, "run_blocked", stage=run.stage, reason=routing.reason, code=routing.code)
