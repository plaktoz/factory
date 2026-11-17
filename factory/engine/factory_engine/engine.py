"""The engine loop (module 6B): drives runs through their workflows.

The engine is the only writer of run and task state. It takes a run's lock, starts tasks through the injected
WorkerAdapter in waves up to `concurrency`, checkpoints each task worktree, joins the task branches, runs the stage's
gates, and routes the outcome. It never calls an LLM. The tracker and pull requests are injected, so tests use fakes.

A pass (`tick`) does the ready work of one run. `run` repeats passes until every run is done, failed, aborted, blocked
or waiting on a person, then releases the locks and returns.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import (decisions, delivery, gates, gitops, housekeeping, notes, notify, rework, shims, skills, state, summary,
               triage)
from . import usage as usage_mod
from . import workflow as wf_mod
from .adapters.worker.base import AttemptResult, HarnessConfig, TaskContext, WorkerAdapter
from .adapters.worker.command import CommandAdapter
from .clock import SystemClock
from .config import Config
from .errors import FactoryError
from .lock import Lock
from .types import (AttentionItem, Clock, GateContext, GateResult, Request, Run, RunStatus, Stage, StageState,
                    TaskBranch, TaskSpec, TaskState, Workflow)
from .workflow import expand_helpers

TRIAGE = "_triage"
DEFAULT_MAX_INTERRUPTIONS = 3
POLL_SECONDS = 0.05  # how often the main thread looks at running workers; a restart waits for the next checkpoint
# Run statuses that end a run, and those where the engine waits for a person or for infrastructure.
ENDED: frozenset[str] = frozenset({"done", "failed", "aborted"})
PARKED: frozenset[str] = frozenset({"awaiting_approval", "blocked", "retrying"})


@dataclass
class TickResult:
    started: list[str] = field(default_factory=list)
    finished: list[str] = field(default_factory=list)
    gates: list[GateResult] = field(default_factory=list)
    routed_to: str | None = None
    attention: AttentionItem | None = None


@dataclass
class EngineResult:
    runs: dict[str, RunStatus]
    exit_code: int


@dataclass
class _Running:
    """One worker the engine is supervising: its task, its handle, the thread waiting on it, and its result."""

    spec: TaskSpec
    harness: str
    handle: object
    ts: TaskState
    thread: threading.Thread = field(default=None)  # type: ignore[assignment]
    outcome: AttemptResult | None = None
    restart_for_note: bool = False


class Engine:
    """One engine process. It holds a run's lock while it drives the run, and releases it when the run waits or ends."""

    def __init__(self, repo: Path, cfg: Config, *, workers: dict[str, WorkerAdapter], tracker, prs,
                 command: WorkerAdapter | None = None, clock: Clock = SystemClock(), owner: str | None = None):
        self.repo = repo
        self.cfg = cfg
        self.workers = workers
        self.command = command if command is not None else CommandAdapter()
        self.tracker = tracker
        self.prs = prs
        self.clock = clock
        self.owner = owner or "engine"
        self.home = state.factory_home()
        self.key = state.repo_key(repo, cfg)

    # ---- public --------------------------------------------------------------------------------------------------

    def run(self, run_ids: list[str] | None = None, *, poll_seconds: int = 5) -> EngineResult:
        """Drive each run until it is done, failed, aborted, blocked or awaiting a human. Holds each run's lock."""
        targets = run_ids or [r.run_id for r in state.list_runs(self.home, key=self.key)]
        statuses: dict[str, RunStatus] = {rid: self._drive(rid) for rid in targets}
        values = set(statuses.values())
        code = 4 if "blocked" in values else 3 if "awaiting_approval" in values else 1 if "failed" in values else 0
        return EngineResult(runs=statuses, exit_code=code)

    def tick(self, run_id: str) -> TickResult:
        """One pass over a run. Takes the run's lock for the pass and releases it before returning."""
        run_dir = self._run_dir(run_id)
        lock = state.acquire_lock(run_dir, self.owner)
        try:
            return self._pass(run_dir, lock)
        finally:
            state.release(lock)

    def resume(self, run_id: str, *, force: bool = False) -> None:
        """Continue a run whose lock is free (module 6B recovery). A live lock refuses, unless `force` is set.

        Open attempts are closed as interrupted, each interrupted task's worktree goes back to its last checkpoint, and
        the diff that was discarded is saved as `discarded-<n>.patch`."""
        run_dir = self._run_dir(run_id)
        if not force and state.lock_status(run_dir) == "live":
            raise FactoryError("state.locked", f"run {run_id} is held by a live engine",
                               hint="wait for that engine, or stop it, then resume")
        lock = state.acquire_lock(run_dir, self.owner)
        try:
            self._recover(run_dir, lock)
        finally:
            state.release(lock)
        self._drive(run_id)

    def stop(self, run_id: str, *, reason: str) -> None:
        """Abort a run, close its open attempts and record why. A run that has ended is left alone."""
        run_dir = self._run_dir(run_id)
        lock = state.acquire_lock(run_dir, self.owner)
        try:
            run = state.read_run(run_dir)
            if run.status in ENDED:
                return
            usage_mod.close_open_attempts(run_dir)
            run.status, run.attention = "aborted", None
            state.write_run(run_dir, run, lock=lock)
            state.append_event(run_dir, "run_aborted", reason=reason)
        finally:
            state.release(lock)

    # ---- blocked-run actions (module 8, driven by module 16) -------------------------------------------------------

    def retry(self, run_id: str, *, stage: str | None = None, note: str | None = None, by: str = "cli") -> None:
        """Run a blocked stage once more. The note, if any, is queued on that stage's tasks and reaches the worker as
        feedback. Loop counters stay as they are: a retry is one more attempt, not another loop."""
        run_dir, lock, run, wf = self._blocked(run_id)
        try:
            target = self._stage_of(wf, stage or run.stage)
            for spec in self._specs(target, run_dir):
                if (run_dir / "tasks" / spec.id / "task.json").is_file() and state.read_task(run_dir, spec.id).status == "failed":
                    (run_dir / "tasks" / spec.id / "task.json").unlink()  # a failed task starts again with a fresh state
                if note and note.strip():
                    self._task_state(run_dir, lock, target, spec)  # a fresh pending task can take the note
                    notes.queue_note(run_dir, spec.id, note.strip(), by=by)
            self._unblock(run, run_dir, lock, target.id)
            state.append_event(run_dir, "run_retried", stage=target.id, by=by, note=bool(note and note.strip()))
        finally:
            state.release(lock)

    def goto(self, run_id: str, stage: str, *, by: str = "cli") -> None:
        """Send a blocked run to any earlier stage. That stage and every later one start again, with no loop limit,
        because a person chose the route."""
        run_dir, lock, run, wf = self._blocked(run_id)
        try:
            target = self._stage_of(wf, stage)
            order = [s.id for s in wf.stages]
            if run.stage in order and order.index(target.id) > order.index(run.stage):
                raise FactoryError("config.invalid", f"{target.id!r} is after the blocked stage {run.stage!r}",
                                   hint="goto sends a run back to this stage or an earlier one")
            reset = rework._reset_from(run, wf, target.id)
            self._reset_tasks(run_dir, wf, reset)
            self._unblock(run, run_dir, lock, target.id)
            state.append_event(run_dir, "run_routed", to_stage=target.id, reset=reset, by=by)
        finally:
            state.release(lock)

    def skip(self, run_id: str, gate: str, *, reason: str, by: str = "cli") -> None:
        """Pass a gate the workflow marks `skippable: true`. The skip is logged with its reason, and the stage is
        marked skipped, which stops auto-merge (module 13). A gate that is not marked refuses."""
        if not reason or not reason.strip():
            raise FactoryError("config.invalid", "a skip needs a reason", hint='pass --reason "why this gate is passed"')
        run_dir, lock, run, wf = self._blocked(run_id)
        try:
            stage = self._stage_of(wf, run.stage)
            spec = next((g for g in stage.gate if gates.gate_name(g) == gate), None)
            if spec is None:
                names = ", ".join(gates.gate_name(g) for g in stage.gate) or "none"
                raise FactoryError("config.invalid", f"stage {stage.id!r} has no gate named {gate!r} (gates: {names})",
                                   hint="copy the gate name from the blocked card or from a gate_failed event")
            if not spec.skippable:
                raise FactoryError("config.invalid", f"gate {gate!r} is not marked skippable",
                                   hint="add `skippable: true` to the gate in the workflow file")
            state.append_event(run_dir, "gate_skipped", stage=stage.id, gate=gate, reason=reason.strip(), by=by)
            self._set_stage(run, stage.id, "skipped").ended = self.clock.now().isoformat()
            self._unblock(run, run_dir, lock, self._next_stage_id(wf, stage.id))
        finally:
            state.release(lock)

    def _blocked(self, run_id: str):
        """Take the run's lock and load a blocked run and its workflow. Refuses a run that is not blocked."""
        run_dir = self._run_dir(run_id)
        lock = state.acquire_lock(run_dir, self.owner)
        try:
            run = state.read_run(run_dir)
            if run.status != "blocked":
                raise FactoryError("config.invalid", f"run {run_id} is not blocked (it is {run.status})",
                                   hint="retry, goto and skip apply to a blocked run")
            if run.workflow is None:
                raise FactoryError("config.invalid", f"run {run_id} is blocked before a workflow was chosen",
                                   hint="set the request type and retry from triage")
            return run_dir, lock, run, self._load(run.workflow)
        except BaseException:
            state.release(lock)
            raise

    @staticmethod
    def _stage_of(wf: Workflow, stage_id: str | None) -> Stage:
        found = next((s for s in wf.stages if s.id == stage_id), None)
        if found is None:
            raise FactoryError("config.invalid", f"{stage_id!r} is not a stage of {wf.name}",
                               hint="stages: " + ", ".join(s.id for s in wf.stages))
        return found

    @staticmethod
    def _next_stage_id(wf: Workflow, stage_id: str) -> str | None:
        order = [s.id for s in wf.stages]
        i = order.index(stage_id) + 1
        return order[i] if i < len(order) else None

    def _unblock(self, run: Run, run_dir: Path, lock: Lock, stage_id: str | None) -> None:
        run.status, run.attention, run.stage = "running", None, stage_id
        state.write_run(run_dir, run, lock=lock)

    # ---- the loop ------------------------------------------------------------------------------------------------

    def _drive(self, run_id: str) -> RunStatus:
        """Pass after pass until the run ends or parks. The lock is held across the passes and released at the end."""
        run_dir = self._run_dir(run_id)
        lock = state.acquire_lock(run_dir, self.owner)
        try:
            for _ in range(10_000):  # a bound, so a routing bug cannot spin forever
                run = state.read_run(run_dir)
                if run.status in ENDED or run.status in PARKED:
                    if run.status != "awaiting_approval":
                        return run.status
                    self._pass(run_dir, lock)  # an answered stop moves on; an unanswered one stays parked
                    if state.read_run(run_dir).status == "awaiting_approval":
                        return "awaiting_approval"
                    continue
                self._pass(run_dir, lock)
            raise FactoryError("config.invalid", f"run {run_id} made no progress in 10000 passes",
                               hint="a routing loop is not reaching a stop; check the workflow's on_fail edges")
        finally:
            state.release(lock)

    def _pass(self, run_dir: Path, lock: Lock) -> TickResult:
        run = state.read_run(run_dir)
        result = TickResult()
        if run.status == "awaiting_approval":
            return self._answered_stop(run, run_dir, lock, result)
        if run.status in ENDED or run.status in PARKED:
            return result
        if run.workflow is None:
            return self._triage(run, run_dir, lock, result)
        wf = self._load(run.workflow)
        stage = self._current_stage(run, wf)
        if stage is None:
            return self._finish(run, run_dir, lock, result)
        if not self._stage_ready(run, stage):
            return result
        if stage.approval == "human" and self._stage_finished(run_dir, stage):
            return self._human_stop(run, run_dir, lock, wf, stage, result)
        return self._run_stage(run, run_dir, lock, wf, stage, result)

    def _answered_stop(self, run: Run, run_dir: Path, lock: Lock, result: TickResult) -> TickResult:
        """A run waiting on a person. An answer already in the decision file moves it on (module 6, lifecycle step 4):
        a triage answer continues the triage stage, an approval answer goes through the stage's human stop. An
        unanswered stop stays parked, and nothing is written."""
        stage_id = next((s.id for s in run.stages if s.status == "awaiting_approval"), run.stage)
        visit = decisions.latest_visit(run, stage_id)
        if decisions.evaluate(run_dir, stage_id, visit).status == "pending":
            return result
        run.status = "running"
        self._set_stage(run, stage_id, "running")
        run.attention = None
        state.write_run(run_dir, run, lock=lock)
        if stage_id == "triage":
            return self._triage(run, run_dir, lock, result)
        wf = self._load(run.workflow)
        stage = next(s for s in wf.stages if s.id == stage_id)
        return self._human_stop(run, run_dir, lock, wf, stage, result)

    # ---- triage ----------------------------------------------------------------------------------------------------

    def _triage(self, run: Run, run_dir: Path, lock: Lock, result: TickResult) -> TickResult:
        """Run `_triage`. Its gate must name a type and a workflow; then the chosen workflow's stages are appended."""
        wf = self._load(TRIAGE)
        stage = wf.stages[0]
        self._stage_running(run, run_dir, lock, stage.id)
        self._execute_tasks(run, run_dir, lock, wf, stage, result)
        if not self._stage_finished(run_dir, stage):
            return self._after_tasks(run, run_dir, lock, wf, stage, result)
        artifact = self._triage_artifact(run_dir)
        self._apply_triage_answer(run, run_dir, artifact)
        ctx = GateContext(run=run, stage=stage.id, task_id=None, worktree=run.worktree, task_dir=artifact.parent,
                          artifact=artifact, task_base=None, scope=[], deny=[], cfg=self.cfg)
        results = gates.run_gates(stage.gate, ctx)
        gates.record_gates(run_dir, results)
        result.gates.extend(results)
        if any(not g.passed for g in results):
            return self._triage_stop(run, run_dir, lock, result)
        doc = json.loads(artifact.read_text())
        run.workflow = doc["workflow"]
        run.request = Request(**{**vars(run.request), "type": doc["type"], "type_source": doc["type_source"]})
        self._create_run_worktree(run, run_dir, self._load(run.workflow))
        self._set_stage(run, stage.id, "done").ended = self.clock.now().isoformat()
        state.append_event(run_dir, "stage_done", stage=stage.id, workflow=run.workflow)
        state.write_run(run_dir, run, lock=lock)
        result.finished.append(stage.id)
        return result

    def _apply_triage_answer(self, run: Run, run_dir: Path, artifact: Path) -> None:
        """A person chose the workflow at the triage stop: write the choice into triage.json, so the type-resolved gate
        passes on it and the file records who decided. The answer is a workflow id from the packet's options."""
        visit = decisions.latest_visit(run, "triage")
        if not decisions.decision_path(run_dir, "triage", visit).is_file():
            return
        outcome = decisions.evaluate(run_dir, "triage", visit)
        picked = outcome.choices.get("D1") if outcome.status == "approved" else None
        if picked is None:
            return
        rtype = next((t for t, wid in triage.TYPE_WORKFLOW.items() if wid == picked), None)
        if rtype is None:
            return
        doc = json.loads(artifact.read_text()) if artifact.is_file() else {"schema_version": 1}
        doc.update(type=rtype, workflow=picked, confidence=1.0, type_source="explicit")
        artifact.write_text(json.dumps(doc, indent=2))
        state.append_event(run_dir, "triage_answered", workflow=picked)

    def _triage_artifact(self, run_dir: Path) -> Path:
        return run_dir / "tasks" / "rules" / "work" / "triage.json"

    def _triage_stop(self, run: Run, run_dir: Path, lock: Lock, result: TickResult) -> TickResult:
        """The rules and classify could not pick a workflow: a person chooses (module 4). The options are only the
        workflows that load. With fewer than two there is nothing to choose between, so the run is blocked."""
        candidates = triage.triage_candidates(run.request, self._loads)
        if len(candidates) < 2:
            names = ", ".join(c[0] for c in candidates) or "none"
            routing = rework.route(run, self._load(TRIAGE), self._load(TRIAGE).stages[0], "human")
            routing.reason = run.attention.summary = (
                f"triage could not pick a workflow and only {len(candidates)} loads ({names}); set the request type")
            run.stage = "triage"
            rework.record_blocked(run_dir, run, routing)
            result.attention = run.attention
            state.write_run(run_dir, run, lock=lock)
            return result
        visit = decisions.latest_visit(run, "triage")
        decisions.request(run_dir, "triage", visit, kind="triage", packet=decisions.triage_packet(candidates))
        run.status, run.stage = "awaiting_approval", "triage"
        self._set_stage(run, "triage", "awaiting_approval")
        result.attention = run.attention = notify.attention_for(run, now=self.clock.now().isoformat())
        state.write_run(run_dir, run, lock=lock)
        return result

    def _loads(self, workflow_id: str) -> bool:
        """Whether a workflow loads (module 5). Module 4 asks through this, because it may not import module 5."""
        try:
            self._load(workflow_id)
            return True
        except FactoryError:
            return False

    def _create_run_worktree(self, run: Run, run_dir: Path, chosen: Workflow) -> None:
        """Triage ended: the chosen workflow's policy.write decides between a branch and a detached worktree (module 4)."""
        base = (self.cfg.repo or {}).get("base_branch", "main")
        detached = not chosen.policy.write
        run.worktree = gitops.create_run_worktree(self.repo, self.cfg, run.run_id, base=base, detached=detached)
        run.branch = None if detached else run.run_id
        run.paths["worktree"] = str(run.worktree)
        gitops.mark_run(run.worktree, run_dir, run.run_id, run.repo_key)
        wanted = [spec.skill for st in chosen.stages for spec in st.tasks if spec.skill]
        refs = [skills.resolve_skill(name, self.repo, self.cfg) for name in dict.fromkeys(wanted)]
        shims.generate_shims(run.worktree, ["claude"], refs)

    # ---- stages ----------------------------------------------------------------------------------------------------

    def _current_stage(self, run: Run, wf: Workflow) -> Stage | None:
        done = {s.id for s in run.stages if s.status in ("done", "skipped")}
        return next((s for s in wf.stages if s.id not in done), None)

    def _stage_ready(self, run: Run, stage: Stage) -> bool:
        done = {s.id for s in run.stages if s.status in ("done", "skipped")}
        return all(n in done for n in stage.needs)

    def _stage_running(self, run: Run, run_dir: Path, lock: Lock, stage_id: str) -> None:
        st = self._set_stage(run, stage_id, "running")
        if st.started is None:
            st.started = self.clock.now().isoformat()
            state.append_event(run_dir, "stage_started", stage=stage_id)
        run.stage, run.status = stage_id, "running"
        state.write_run(run_dir, run, lock=lock)

    def _set_stage(self, run: Run, stage_id: str, status: str) -> StageState:
        st = next((s for s in run.stages if s.id == stage_id), None)
        if st is None:
            st = StageState(id=stage_id, visit=1, status="pending", tasks=[], started=None, ended=None)
            run.stages.append(st)
        st.status = status
        return st

    def _run_stage(self, run: Run, run_dir: Path, lock: Lock, wf: Workflow, stage: Stage, result: TickResult) -> TickResult:
        self._stage_running(run, run_dir, lock, stage.id)
        self._execute_tasks(run, run_dir, lock, wf, stage, result)
        if not self._stage_finished(run_dir, stage):
            return self._after_tasks(run, run_dir, lock, wf, stage, result)
        if stage.approval == "human":
            return self._human_stop(run, run_dir, lock, wf, stage, result)
        return self._join_and_gate(run, run_dir, lock, wf, stage, result)

    def _specs(self, stage: Stage, run_dir: Path | None = None) -> list[TaskSpec]:
        if stage.tasks_from and run_dir is not None:
            return wf_mod.expand_tasks_from(stage, run_dir / "tasks" / stage.tasks_from)
        first = next(iter(self.workers.values()), None)  # the blocked-run actions build an engine with no worker
        native = first.capabilities.subagents if first is not None else False
        out: list[TaskSpec] = []
        for spec in stage.tasks:
            out.extend(expand_helpers(spec, native))
        return out

    def _stage_finished(self, run_dir: Path, stage: Stage) -> bool:
        """Every task of the stage has a state and is done."""
        return all(self._status_of(run_dir, s.id) == "done" for s in self._specs(stage, run_dir))

    def _after_tasks(self, run: Run, run_dir: Path, lock: Lock, wf: Workflow, stage: Stage, result: TickResult) -> TickResult:
        """A task that failed for good blocks the run: when retries run out the run is blocked (module 8)."""
        if any(self._status_of(run_dir, s.id) == "failed" for s in self._specs(stage, run_dir)):
            return self._apply(run, run_dir, lock, wf, stage, rework.route(run, wf, stage, "human"), result)
        return result

    # ---- tasks -----------------------------------------------------------------------------------------------------

    def _concurrency(self) -> int:
        return int((self.cfg.repo or {}).get("concurrency", 4))

    def _slots(self, spec: TaskSpec) -> int:
        """A task with a helper maximum of 2 reserves 3 slots: itself and its helpers (module 6B scheduler)."""
        return 1 + (spec.helpers.max if spec.helpers.mode != "off" else 0)

    def _status_of(self, run_dir: Path, task_id: str) -> str:
        path = run_dir / "tasks" / task_id / "task.json"
        return state.read_task(run_dir, task_id).status if path.is_file() else "none"

    def _execute_tasks(self, run: Run, run_dir: Path, lock: Lock, wf: Workflow, stage: Stage, result: TickResult) -> None:
        """Start ready tasks together up to the concurrency limit, wait for them, and record each result. Repeats while
        a finished task makes another ready. A task that failed for good stops the loop."""
        specs = self._specs(stage, run_dir)
        while True:
            statuses = {s.id: self._status_of(run_dir, s.id) for s in specs}
            if any(st == "failed" for st in statuses.values()):
                return
            done = {t for t, st in statuses.items() if st == "done"}
            ready = [s for s in specs if statuses[s.id] in ("none", "pending", "interrupted")
                     and all(n in done for n in s.needs)]
            skipped = [s for s in ready if not self._when_holds(s, run_dir)]
            for spec in skipped:
                self._skip_task(run_dir, lock, stage, spec)
            ready = [s for s in ready if s not in skipped]
            if skipped and not ready:
                continue
            if not ready:
                return
            batch, used = [], 0
            for spec in ready:
                if batch and used + self._slots(spec) > self._concurrency():
                    break
                batch.append(spec)
                used += self._slots(spec)
            self._supervise(run, run_dir, lock, wf, stage, batch, result)

    def _when_holds(self, spec: TaskSpec, run_dir: Path) -> bool:
        """The task's `when` condition (module 5). `confidence_below` reads triage.json; other forms always hold here."""
        when = spec.when
        if not when or "confidence_below" not in when:
            return True
        artifact = self._triage_artifact(run_dir)
        if not artifact.is_file():
            return True
        return float(json.loads(artifact.read_text()).get("confidence", 0.0)) < float(when["confidence_below"])

    def _skip_task(self, run_dir: Path, lock: Lock, stage: Stage, spec: TaskSpec) -> None:
        ts = TaskState(task_id=spec.id, stage=stage.id, status="done", attempt=0, restarts=0,
                       task_base=None, worktree=None, checkpoints=0)
        state.task_dir(run_dir, spec.id)
        state.write_task(run_dir, ts, lock=lock)
        state.append_event(run_dir, "task_created", task_id=spec.id, stage=stage.id, skipped=True)

    def _task_state(self, run_dir: Path, lock: Lock, stage: Stage, spec: TaskSpec) -> TaskState:
        if (run_dir / "tasks" / spec.id / "task.json").is_file():
            return state.read_task(run_dir, spec.id)
        state.task_dir(run_dir, spec.id)
        ts = TaskState(task_id=spec.id, stage=stage.id, status="pending", attempt=0, restarts=0,
                       task_base=None, worktree=None, checkpoints=0)
        state.write_task(run_dir, ts, lock=lock)
        state.append_event(run_dir, "task_created", task_id=spec.id, stage=stage.id)
        return ts

    def _start_task(self, run: Run, run_dir: Path, lock: Lock, wf: Workflow, stage: Stage, spec: TaskSpec):
        """Write the attempt's usage record, then start the worker. The record comes first (write-ahead, module 14)."""
        ts = self._task_state(run_dir, lock, stage, spec)
        if wf.name == TRIAGE:
            worktree = state.task_dir(run_dir, spec.id) / "work"  # triage has no repo (module 4)
            worktree.mkdir(parents=True, exist_ok=True)
        else:
            worktree = ts.worktree or gitops.create_task_worktree(
                self.repo, self.cfg, run.run_id, spec.id,
                base_branches=[f"{run.run_id}--{n}" for n in spec.needs] or [run.run_id])
            ts.task_base = f"{run.run_id}--{spec.needs[0]}" if spec.needs else run.run_id
        ts.worktree = worktree
        harness = self._harness_of(spec)
        attempt = usage_mod.start_attempt(run_dir, run, spec.id, stage=stage.id, harness=harness, model_requested=spec.model)
        ts.attempt, ts.status = attempt, "running"
        state.write_task(run_dir, ts, lock=lock)
        stage_state = next(s for s in run.stages if s.id == stage.id)
        if spec.id not in stage_state.tasks:
            stage_state.tasks.append(spec.id)
        state.write_run(run_dir, run, lock=lock)
        self._deliver_notes(run_dir, spec, attempt)
        if self._request_copy_for(run_dir, spec):
            self._copy_request(run_dir, spec)
        ctx = self._context(run, run_dir, stage, spec, attempt, worktree)
        handle = self._worker_for(spec).start(ctx, HarnessConfig(harness, None, [], {}), run_dir / "tasks" / spec.id / "worker.log")
        return spec, (harness, handle), ts

    def _request_copy_for(self, run_dir: Path, spec: TaskSpec) -> bool:
        """A deterministic task gets a copy of the run's request.json in its work folder: the sandbox denies reads of the
        factory home, where the request lives (ADR 2026-11-17-factory-triage-reads-its-request-from-the-task-folder)."""
        return self._is_deterministic(spec) and (run_dir / "request.json").is_file()

    @staticmethod
    def _copy_request(run_dir: Path, spec: TaskSpec) -> None:
        import shutil
        work = run_dir / "tasks" / spec.id / "work"
        work.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run_dir / "request.json", work / "request.json")

    def _worker_for(self, spec: TaskSpec) -> WorkerAdapter:
        """A deterministic task (cmd, script or python) runs through CommandAdapter; a skill task goes to the worker
        registered for the configured harness (module 9, Deterministic tasks)."""
        return self.command if self._is_deterministic(spec) else self.workers[self._harness_of(spec)]

    def _harness_of(self, spec: TaskSpec) -> str:
        return self.command.name if self._is_deterministic(spec) else next(iter(self.workers))

    @staticmethod
    def _is_deterministic(spec: TaskSpec) -> bool:
        return spec.cmd is not None or spec.run is not None

    def _adapter_named(self, harness: str) -> WorkerAdapter:
        return self.command if harness == self.command.name else self.workers[harness]

    def _deliver_notes(self, run_dir: Path, spec: TaskSpec, attempt: int) -> None:
        pending = notes.pending_notes(run_dir, spec.id)
        if pending:
            notes.mark_delivered(run_dir, spec.id, [n.id for n in pending], attempt=attempt)  # logs note_delivered

    def _context(self, run: Run, run_dir: Path, stage: Stage, spec: TaskSpec, attempt: int, worktree: Path) -> TaskContext:
        task_dir = run_dir / "tasks" / spec.id / "work"
        task_dir.mkdir(parents=True, exist_ok=True)
        skill = skills.resolve_skill(spec.skill, self.repo, self.cfg) if spec.skill else None
        return TaskContext(
            run_id=run.run_id, task_id=spec.id, stage=stage.id, attempt=attempt, skill=skill, request=run.request,
            worktree=worktree, task_dir=task_dir, scope=list(spec.scope), deny=list(spec.deny), helpers=spec.helpers,
            feedback=sorted((run_dir / "tasks" / spec.id / "feedback").glob("*.json")),
            notes=notes.delivered_notes(run_dir, spec.id), progress=None, output_schema=None, model=spec.model,
            mcp=[], practices=[], artifact_name=spec.out or "artifact.json", bash=[],
            cmd=list(spec.cmd) if spec.cmd else None, run=spec.run, plugin_dir=None)

    def _supervise(self, run: Run, run_dir: Path, lock: Lock, wf: Workflow, stage: Stage, batch: list[TaskSpec],
                   result: TickResult) -> None:
        """Run a batch of tasks together. Each worker's `wait` runs in its own thread, because `wait` kills the worker at
        its timeout and cannot be polled. This thread owns the lock and does every state write: it records results,
        checkpoints, and restarts a worker when a note is queued (module 12). The threads only call `wait`."""
        running: dict[str, _Running] = {}
        for spec in batch:
            running[spec.id] = self._launch(run, run_dir, lock, wf, stage, spec)
        while running:
            for task_id in list(running):
                job = running[task_id]
                if job.thread.is_alive():
                    self._maybe_restart(run_dir, lock, job)
                    continue
                job.thread.join()
                del running[task_id]
                self._record_result(run_dir, lock, job, result)
                if job.restart_for_note and job.outcome is not None:
                    running[task_id] = self._launch(run, run_dir, lock, wf, stage, job.spec)
            if running:
                self.clock.sleep(POLL_SECONDS) if hasattr(self.clock, "advance") else threading.Event().wait(POLL_SECONDS)

    def _launch(self, run: Run, run_dir: Path, lock: Lock, wf: Workflow, stage: Stage, spec: TaskSpec) -> "_Running":
        spec_, (harness, handle), ts = self._start_task(run, run_dir, lock, wf, stage, spec)
        job = _Running(spec=spec_, harness=harness, handle=handle, ts=ts)

        def wait() -> None:
            job.outcome = self._adapter_named(harness).wait(handle, spec_.timeout_minutes * 60)

        job.thread = threading.Thread(target=wait, name=f"worker-{spec_.id}", daemon=True)
        job.thread.start()
        return job

    def _maybe_restart(self, run_dir: Path, lock: Lock, job: "_Running") -> None:
        """A note is queued for a running task: at a checkpoint the engine stops the worker so it restarts with the note
        (module 12). Each restart counts toward max_restarts; at the cap the note stays queued."""
        if job.restart_for_note or not notes.pending_notes(run_dir, job.spec.id):
            return
        if job.ts.restarts >= self._max_restarts():
            return
        self._checkpoint(job.ts, job.spec)
        job.ts.restarts += 1
        job.ts.status = "restarting"
        state.write_task(run_dir, job.ts, lock=lock)
        state.append_event(run_dir, "worker_restarted", task_id=job.spec.id, restarts=job.ts.restarts)
        job.restart_for_note = True
        self._adapter_named(job.harness).stop(job.handle)

    def _max_restarts(self) -> int:
        return int((self.cfg.repo or {}).get("max_restarts", 3))

    def _record_result(self, run_dir: Path, lock: Lock, job: "_Running", result: TickResult) -> None:
        outcome, ts, spec = job.outcome, job.ts, job.spec
        if outcome is None:  # the thread died without a result: treat it as a crash
            outcome = AttemptResult("failed", None, None, None, None, [], "crash")
        ok = outcome.exit == "ok" and outcome.artifact is not None
        exit_ = "ok" if ok else "interrupted" if (outcome.exit == "killed" or job.restart_for_note) else "failed"
        usage_mod.finish_attempt(run_dir, spec.id, ts.attempt, exit=exit_, input_tokens=outcome.input_tokens,
                                 output_tokens=outcome.output_tokens, models=outcome.models_observed)
        if job.restart_for_note and not ok:
            self._reset_to_checkpoint(run_dir, ts, spec.id)
            ts.status = "pending"
        elif ok:
            self._checkpoint(ts, spec)
            ts.status = "done"
        else:
            self._after_failed_attempt(run_dir, ts, spec, outcome)
        state.write_task(run_dir, ts, lock=lock)
        result.started.append(spec.id)

    def _checkpoint(self, ts: TaskState, spec: TaskSpec) -> None:
        """Commit the task worktree's changes as a checkpoint. A triage task has no repo, so it has none."""
        if ts.worktree is not None and (ts.worktree / ".git").exists():
            if gitops.checkpoint(ts.worktree, spec.id, ts.checkpoints + 1):
                ts.checkpoints += 1

    def _after_failed_attempt(self, run_dir: Path, ts: TaskState, spec: TaskSpec, outcome: AttemptResult) -> None:
        """A worker error starts a new attempt from the last checkpoint, up to `retries` (module 8)."""
        self._reset_to_checkpoint(run_dir, ts, spec.id)
        if rework.classify(outcome) == "task_retry" and rework.may_retry(ts.attempt, spec.retries):
            ts.status = "pending"
        else:
            ts.status = "failed"

    def _reset_to_checkpoint(self, run_dir: Path, ts: TaskState, task_id: str) -> None:
        """Put the task worktree back at its last checkpoint. The discarded diff is saved first (module 6B recovery)."""
        wt = ts.worktree
        if wt is None or not (wt / ".git").exists():
            return
        # `git diff` ignores a file the worker just created, so mark new files with intent-to-add first. The marker
        # file and the shims are not the worker's work and stay out (module 7: never committed).
        gitops.git(wt, "add", "-N", "--all", check=False)
        for path in gitops.NEVER_COMMITTED:
            gitops.git(wt, "reset", "-q", "--", path, check=False)
        diff = gitops.git(wt, "diff", "HEAD", check=False).stdout
        if diff.strip():
            n = len(list((run_dir / "tasks" / task_id).glob("discarded-*.patch"))) + 1
            (run_dir / "tasks" / task_id / f"discarded-{n}.patch").write_text(diff)
        gitops.git(wt, "reset", "--hard", check=False)
        gitops.git(wt, "clean", "-fd", "-e", ".factory-run.json", "-e", ".claude/skills/factory-*", check=False)

    # ---- recovery --------------------------------------------------------------------------------------------------

    def _recover(self, run_dir: Path, lock: Lock) -> None:
        """After a crash: close open attempts as interrupted, reset those tasks to their last checkpoint, and let them
        run again as new attempts. A task interrupted too often is failed (module 8: max_interruptions)."""
        closed = usage_mod.close_open_attempts(run_dir)
        run = state.read_run(run_dir)
        for task_id, _attempt in closed:
            ts = state.read_task(run_dir, task_id)
            self._reset_to_checkpoint(run_dir, ts, task_id)
            interruptions = sum(1 for r in usage_mod.read_usage(run_dir, task_id) if r.exit == "interrupted")
            ts.status = "failed" if interruptions > DEFAULT_MAX_INTERRUPTIONS else "interrupted"
            state.write_task(run_dir, ts, lock=lock)
            state.append_event(run_dir, "task_interrupted", task_id=task_id, attempt=ts.attempt)
        run.status = "running"
        state.write_run(run_dir, run, lock=lock)
        state.append_event(run_dir, "run_resumed")

    # ---- join, gates, routing --------------------------------------------------------------------------------------

    def _join_and_gate(self, run: Run, run_dir: Path, lock: Lock, wf: Workflow, stage: Stage, result: TickResult) -> TickResult:
        specs = self._specs(stage, run_dir)
        branches = [TaskBranch(s.id, f"{run.run_id}--{s.id}", state.read_task(run_dir, s.id).task_base or run.run_id)
                    for s in specs]
        pre_join = gitops.git(run.worktree, "rev-parse", "HEAD").stdout.strip()
        join = gitops.join(run.worktree, branches, regenerate=wf.regenerate_at_join, join_cmd=wf.join_cmd)
        if not join.ok:
            routing = rework.route_conflict(run, wf, stage) if join.conflict_files else rework.route(run, wf, stage, "rework")
            if routing.action == "goto":
                rework.build_feedback(run_dir, from_stage=stage.id, to_stage=routing.goto, result=join, loop=routing.loop,
                                      max_loops=routing.max, task_ids=self._tasks_of(wf, routing.goto, run_dir))
            return self._apply(run, run_dir, lock, wf, stage, routing, result)
        base = (self.cfg.repo or {}).get("base_branch", "main")
        run.signals = gitops.conflict_signals(self.repo, run, self._other_runs(run), base)
        report = None
        if any(g.kind == "schema" and g.schema == "test-report" for g in stage.gate):
            report = self._test_report_for_stage(run_dir, [s.id for s in specs])
            if json.loads(report.read_text()).get("total", 0) == 0:
                return self._no_test_results(run, run_dir, lock, wf, stage, specs, result)
        failed = self._run_stage_gates(run, run_dir, wf, stage, specs, result, report=report)
        if failed is not None:
            # A failed gate undoes the join: the run branch goes back to where it was, so the rework starts clean.
            # Unspecified in modules 6 to 8; recorded as a decision in the module 6 file.
            gitops.git(run.worktree, "reset", "--hard", pre_join, check=False)
            routing = rework.route(run, wf, stage, rework.classify(failed))
            if routing.action == "goto":
                rework.build_feedback(run_dir, from_stage=stage.id, to_stage=routing.goto, result=failed, loop=routing.loop,
                                      max_loops=routing.max, task_ids=self._tasks_of(wf, routing.goto, run_dir))
            return self._apply(run, run_dir, lock, wf, stage, routing, result)
        self._set_stage(run, stage.id, "done").ended = self.clock.now().isoformat()
        state.append_event(run_dir, "stage_done", stage=stage.id)
        state.write_run(run_dir, run, lock=lock)
        housekeeping.cleanup_after_join(self.repo, self.cfg, run, [s.id for s in specs])
        result.finished.append(stage.id)
        return result

    def _no_test_results(self, run: Run, run_dir: Path, lock: Lock, wf: Workflow, stage: Stage, specs: list[TaskSpec],
                         result: TickResult) -> TickResult:
        """T1: a verify stage whose tasks report 0 test cases blocks the run, with a reason that names each JUnit file the
        stage expected and did not find or that holds no test case. No pull request opens (module 8)."""
        missing = [s.out for s in specs if s.out and s.out.endswith(".junit.xml")]
        reason = ("no test results: the verify stage reported 0 test cases; expected "
                  + ", ".join(missing or ["a JUnit file"]) + " with at least one test case")
        state.append_event(run_dir, "gate_failed", gate="test-report", code="gate.no_test_results", stage=stage.id)
        return self._apply(run, run_dir, lock, wf, stage, rework.block(run, stage.id, reason, self.clock.now()), result)

    def _test_report_for_stage(self, run_dir: Path, task_ids: list[str]) -> Path:
        """Write the stage's test-report.json from its tasks' JUnit files (module 5). The engine owns the file, so it
        lives in the run folder, not in a task's work folder; the {schema: test-report} gate reads it there."""
        junit = [p for t in task_ids for p in (run_dir / "tasks" / t / "work").glob("*.junit.xml")]
        return gates.write_test_report(junit, run_dir / "test-report.json")

    def _run_stage_gates(self, run: Run, run_dir: Path, wf: Workflow, stage: Stage, specs: list[TaskSpec],
                         result: TickResult, *, report: Path | None = None) -> GateResult | None:
        """The stage's gates run once for each task, each with that task's own scope, deny paths, base and artifact
        (the checks read them). Returns the first failure, or None when every gate passed for every task."""
        for spec in specs:
            ts = state.read_task(run_dir, spec.id)
            artifact = run_dir / "tasks" / spec.id / "work" / (spec.out or "artifact.json")
            denied = [*spec.deny, *wf.policy.deny_paths, *notes.delivered_deny(run_dir, spec.id)]
            if report is not None:
                artifact = report  # the test-report gate reads the stage's report, not one task's JUnit file
            ctx = GateContext(run=run, stage=stage.id, task_id=spec.id, worktree=ts.worktree or run.worktree,
                              task_dir=run_dir / "tasks" / spec.id / "work", artifact=artifact if artifact.is_file() else None,
                              task_base=ts.task_base, scope=list(spec.scope), deny=denied, cfg=self.cfg)
            results = gates.run_gates(stage.gate, ctx)
            gates.record_gates(run_dir, results)
            result.gates.extend(results)
            failed = next((g for g in results if not g.passed), None)
            if failed is not None:
                return failed
        return None

    def _tasks_of(self, wf: Workflow, stage_id: str, run_dir: Path) -> list[str]:
        stage = next(s for s in wf.stages if s.id == stage_id)
        return [s.id for s in self._specs(stage, run_dir)]

    def _other_runs(self, run: Run) -> list[Run]:
        return [state.read_run(r.run_dir) for r in state.list_runs(self.home, key=run.repo_key) if r.run_id != run.run_id]

    def _human_stop(self, run: Run, run_dir: Path, lock: Lock, wf: Workflow, stage: Stage, result: TickResult) -> TickResult:
        """The stage's work is done and it needs approval. With no answer the run waits as awaiting_approval, and the
        engine lets go of the run (module 11: an answer starts a new engine)."""
        visit = decisions.latest_visit(run, stage.id)
        if not decisions.decision_path(run_dir, stage.id, visit).is_file():
            decisions.request(run_dir, stage.id, visit, kind="approval")
        outcome = decisions.evaluate(run_dir, stage.id, visit)
        if outcome.status == "pending":
            self._set_stage(run, stage.id, "awaiting_approval")
            run.status, run.stage = "awaiting_approval", stage.id
            result.attention = run.attention = notify.attention_for(run, now=self.clock.now().isoformat())
            state.write_run(run_dir, run, lock=lock)
            return result
        if outcome.status == "approved":
            self._set_stage(run, stage.id, "done").ended = self.clock.now().isoformat()
            run.status = "running"
            state.write_run(run_dir, run, lock=lock)
            result.finished.append(stage.id)
            return result
        return self._apply(run, run_dir, lock, wf, stage, rework.route(run, wf, stage, outcome), result)

    def _apply(self, run: Run, run_dir: Path, lock: Lock, wf: Workflow, stage: Stage, routing: rework.Routing,
               result: TickResult) -> TickResult:
        if routing.action == "goto":
            run.stage, run.status = routing.goto, "running"
            self._reset_tasks(run_dir, wf, routing.reset)
        elif routing.action == "blocked":
            rework.record_blocked(run_dir, run, routing)
            result.attention = run.attention  # route() set the blocked item with its retry command
        elif routing.action == "aborted":
            state.append_event(run_dir, "run_aborted", reason=routing.reason)
        elif routing.action == "wait":
            rework.start_infra_wait(run, operation=stage.id, error=FactoryError("git.network", routing.reason),
                                    clock=self.clock)
        state.write_run(run_dir, run, lock=lock)
        result.routed_to = routing.goto
        return result

    def _reset_tasks(self, run_dir: Path, wf: Workflow, stage_ids: list[str]) -> None:
        """Tasks of the stages sent back start again: their task.json goes, so each gets a fresh state."""
        needs: dict[str, list[str]] = {}
        for sid in stage_ids:
            stage = next(s for s in wf.stages if s.id == sid)
            for spec in self._specs(stage, run_dir):
                needs[spec.id] = list(spec.needs)
                (run_dir / "tasks" / spec.id / "task.json").unlink(missing_ok=True)
        if stage_ids and wf.name != TRIAGE:
            # The old task worktrees and branches go, dependents first, so the next attempt starts from the run branch.
            gitops.delete_chained_branches(self.repo, self.run_id_of(run_dir), {t: n for t, n in needs.items()})

    @staticmethod
    def run_id_of(run_dir: Path) -> str:
        return run_dir.name

    # ---- finish ----------------------------------------------------------------------------------------------------

    def _finish(self, run: Run, run_dir: Path, lock: Lock, result: TickResult) -> TickResult:
        """Every stage is done: write the summary, deliver through the sink, and mark the run done."""
        summary.render_summary(run_dir, usage_mod.summarize([run_dir]))
        sink = delivery.write_sink(run_dir, self.cfg, tracker=self.tracker, prs=self.prs)
        if sink.pr is not None:
            run.pr = sink.pr
        run.status = "done"
        state.write_run(run_dir, run, lock=lock)
        state.append_event(run_dir, "run_done", sink=sink.sink, target=sink.target)
        return result

    # ---- helpers ---------------------------------------------------------------------------------------------------

    def _run_dir(self, run_id: str) -> Path:
        ref = state.find_run(self.home, run_id)
        if ref is None:
            raise FactoryError("config.invalid", f"no run named {run_id!r} in {self.home}", hint="check the run id")
        return ref.run_dir

    def _load(self, name: str) -> Workflow:
        return wf_mod.load_workflow(self.repo, self.cfg, name)
