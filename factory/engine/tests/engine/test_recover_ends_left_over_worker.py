"""Item 63, step 3: `Engine._recover` ends a worker group that a crashed engine left running, before it resets the task and
starts a new attempt.

The PID-reuse guard: a worker is launched after its attempt's `started` record is written, so its group leader started
at or after that record. A process that started before the record cannot be the worker, so the engine leaves it alone.

Every process a test starts is killed in a `finally` block.
"""

import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timedelta

import pytest

from factory_engine import state, usage
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
from factory_engine.engine import Engine
from factory_engine.types import TaskState

from engine_helpers import TRIAGE_JSON


def _alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def _sleeper() -> subprocess.Popen:
    """A process in its own session, as the real adapters start a worker, so its pid is its group id."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _start_attempt(run_dir, task_id: str) -> None:
    """The write-ahead record of an attempt, as the engine writes it before it launches the worker."""
    usage.start_attempt(run_dir, state.read_run(run_dir), task_id, stage="implement", harness="fake", model_requested=None)


def _record_group(run_dir, task_id: str, pgid: int | None) -> None:
    """task.json as the engine leaves it while the attempt runs, with `pgid` as the worker's group."""
    ts = TaskState(task_id=task_id, stage="implement", status="running", attempt=1, restarts=0, task_base=None,
                   worktree=None, checkpoints=0, worker_pgid=pgid)
    lock = state.acquire_lock(run_dir, "test")
    try:
        state.write_task(run_dir, ts, lock=lock)
    finally:
        state.release(lock)


def _recover(eng, run_dir) -> None:
    lock = state.acquire_lock(run_dir, "test")
    try:
        eng._recover(run_dir, lock)
    finally:
        state.release(lock)


def _set_attempt_start(run_dir, task_id: str, when: datetime) -> None:
    """Rewrite the open attempt's `start` (a test of the guard's clock comparison, not of the engine)."""
    path = run_dir / "tasks" / task_id / "usage.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for rec in lines:
        rec["start"] = when.isoformat(timespec="seconds")
    path.write_text("".join(json.dumps(rec) + "\n" for rec in lines))


@pytest.fixture
def recovering(new_run, repo, cfg, tracker, prs, clock):
    """An engine and a run. The test opens an attempt for task `change` and records the group it wants."""
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))], "change": [ok(work("change", "change.json"))]}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "change": {"change.json": "{}"}}
    worker = FakeWorkerAdapter(script, writes=writes)
    eng = Engine(repo, cfg, workers={"fake": worker}, command=worker, tracker=tracker, prs=prs, clock=clock)
    eng.tick("bump-q1w2e")  # triage: sets run.workflow, which _recover reads for max_interruptions
    return eng, run_dir


def test_a_worker_group_a_crashed_engine_left_running_is_killed_on_recovery(recovering):
    eng, run_dir = recovering
    _start_attempt(run_dir, "change")  # the record comes first: the worker is launched after it
    left = _sleeper()
    try:
        _record_group(run_dir, "change", left.pid)
        assert _alive(left.pid)
        _recover(eng, run_dir)
        assert left.wait(timeout=10) == -signal.SIGKILL
        assert not _alive(left.pid)
        ended = [e.data for e in state.read_events(run_dir) if e.type == "worker_killed"]
        assert ended == [{"task_id": "change", "pgid": left.pid}]
        assert state.read_task(run_dir, "change").worker_pgid is None
    finally:
        if left.poll() is None:
            os.killpg(left.pid, signal.SIGKILL)
            left.wait()


def test_a_group_that_is_already_gone_is_left_alone_and_writes_no_event(recovering):
    eng, run_dir = recovering
    _start_attempt(run_dir, "change")
    gone = _sleeper()
    gone.kill()
    gone.wait()
    _record_group(run_dir, "change", gone.pid)
    _recover(eng, run_dir)
    assert [e for e in state.read_events(run_dir) if e.type == "worker_killed"] == []
    assert state.read_task(run_dir, "change").status == "interrupted"


def test_a_process_that_started_before_the_attempt_is_not_killed(recovering):
    """The recorded pid is alive, but its process started before the attempt's `started` record, so it cannot be the
    worker that record announced. The engine must not signal it."""
    eng, run_dir = recovering
    other = _sleeper()
    try:
        _record_group(run_dir, "change", other.pid)
        _start_attempt(run_dir, "change")
        # The record is written after the process started: rewind it to a time later than the process's start.
        _set_attempt_start(run_dir, "change", datetime.now().astimezone() + timedelta(days=1))
        _recover(eng, run_dir)
        assert other.poll() is None
        assert [e for e in state.read_events(run_dir) if e.type == "worker_killed"] == []
    finally:
        if other.poll() is None:
            os.killpg(other.pid, signal.SIGKILL)
            other.wait()


def test_a_task_with_no_recorded_group_is_recovered_as_before(recovering):
    eng, run_dir = recovering
    _start_attempt(run_dir, "change")
    _record_group(run_dir, "change", None)
    _recover(eng, run_dir)
    assert [e for e in state.read_events(run_dir) if e.type == "worker_killed"] == []
    assert state.read_task(run_dir, "change").status == "interrupted"
