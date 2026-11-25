"""Module 6, crash recovery against a real killed process: the engine is SIGKILLed while its worker runs, then the next
tick's engine is started.

The killed engine and the worker's left-over process group are real processes. Every child is killed in a `finally`,
so a failing test leaves nothing running. The tick's spawn (`api.spawn_engine`) starts `python -m factory_engine run`
with the real Claude adapter, which a test cannot run; the spawned child here calls `Engine.run` with fake workers,
which is what that command calls.

The left-over worker check runs the real recovery path: the killed engine records its worker's process group in task.json
(item 63), and the resumed engine ends that group before it starts attempt 2.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from engine_helpers import chore_script
from factory_engine import state, usage
from factory_engine.adapters.worker.fake import ok
from factory_engine.lock import lock_status

ENGINE_DIR = Path(__file__).resolve().parents[2]
TESTS_DIR = Path(__file__).resolve().parent
KIT = Path(__file__).resolve().parents[3]  # factory/


class NotResumed(AssertionError):
    """The engine a tick starts did not finish the killed run."""


class NotEnded(AssertionError):
    """A worker process the killed engine started is still running after the run was resumed."""


# The engine that gets killed: it starts `change`'s worker, which also starts a process of its own in its own session.
CHILD_KILLED = """
import subprocess, sys, time
from pathlib import Path
sys.path[:0] = [{engine!r}, {tests!r}]
from factory_engine import skills
from factory_engine.adapters.tracker.fake import FakeTracker
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
from factory_engine.clock import FakeClock
from factory_engine.config import Config
from factory_engine.engine import Engine
from factory_engine.fake_prs import FakePullRequests
from engine_helpers import chore_script
skills.use_kit(Path({kit!r}))
run_dir = Path({run_dir!r})
script, writes = chore_script(run_dir, change=[ok(run_dir / "tasks" / "change" / "work" / "change.json")] * 2)


class Hang(FakeWorkerAdapter):
    def start(self, ctx, conf, log):
        handle = super().start(ctx, conf, log)
        if ctx.task_id == "change":
            p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            Path({leftover!r}).write_text(str(p.pid))
            # The real adapters keep their process in handle.data["proc"]; the engine reads its pid as the group id.
            handle.data["proc"] = p
        return handle

    def wait(self, handle, timeout_s):
        if handle.task_id == "change":
            print("RUNNING", flush=True)
            time.sleep(600)
        return handle.data["result"]


w = Hang(script, writes=writes)
cfg = Config(machine={machine!r}, repo={{"base_branch": "main", "concurrency": 4, "infra_wait_hours": 6}})
Engine(Path({repo!r}), cfg, workers={{"fake": w}}, command=w, tracker=FakeTracker(), prs=FakePullRequests(),
       clock=FakeClock()).run(["bump-q1w2e"])
"""

# What the tick's RESUME spawns: a fresh engine that drives the run. Triage is done, so it must not run again.
CHILD_TICK_SPAWN = """
import sys
from pathlib import Path
sys.path[:0] = [{engine!r}, {tests!r}]
from factory_engine import skills
from factory_engine.adapters.tracker.fake import FakeTracker
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
from factory_engine.clock import FakeClock
from factory_engine.config import Config
from factory_engine.engine import Engine
from factory_engine.fake_prs import FakePullRequests
from engine_helpers import chore_script
skills.use_kit(Path({kit!r}))
run_dir = Path({run_dir!r})
script, writes = chore_script(run_dir, change=[ok(run_dir / "tasks" / "change" / "work" / "change.json")] * 2)
script["rules"] = []
w = FakeWorkerAdapter(script, writes=writes)
cfg = Config(machine={machine!r}, repo={{"base_branch": "main", "concurrency": 4, "infra_wait_hours": 6}})
Engine(Path({repo!r}), cfg, workers={{"fake": w}}, command=w, tracker=FakeTracker(), prs=FakePullRequests(),
       clock=FakeClock()).run(["bump-q1w2e"])
"""


def _alive(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _end_group(pid: int | None) -> None:
    if pid is None:
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


@pytest.fixture
def killed_mid_fix(new_run, repo, cfg, tmp_path):
    """An engine SIGKILLed while its `change` worker runs. Yields the run folder and the worker's process group id."""
    run_dir = new_run()
    leftover_file = tmp_path / "leftover.pid"
    code = CHILD_KILLED.format(engine=str(ENGINE_DIR), tests=str(TESTS_DIR), kit=str(KIT), run_dir=str(run_dir),
                               repo=str(repo), machine=cfg.machine, leftover=str(leftover_file))
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, start_new_session=True)
    leftover = None
    try:
        assert child.stdout.readline().strip() == "RUNNING"
        os.kill(child.pid, signal.SIGKILL)
        child.wait()
        leftover = int(leftover_file.read_text())
        assert lock_status(run_dir) == "stale"  # the kernel freed the lock with the process
        assert state.read_run(run_dir).status == "running"
        assert [r.exit for r in usage.read_usage(run_dir, "change")] == ["started"]
        assert _alive(leftover)  # the worker's process group outlived its engine
        yield run_dir, leftover
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        _end_group(leftover)


def test_the_engine_a_tick_spawns_after_a_kill_finishes_the_run(killed_mid_fix, repo, cfg):
    """The tick's RESUME (module 6 table: `running`, lock `stale`): the spawned engine drives the run to its next stop."""
    run_dir, _ = killed_mid_fix
    code = CHILD_TICK_SPAWN.format(engine=str(ENGINE_DIR), tests=str(TESTS_DIR), kit=str(KIT), run_dir=str(run_dir),
                                   repo=str(repo), machine=cfg.machine)
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             start_new_session=True)
    try:
        deadline = time.monotonic() + 30
        while child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.5)
        if child.poll() is None:
            raise NotResumed("the spawned engine has not returned after 30 s; run is "
                             f"{state.read_run(run_dir).status}, change is {state.read_task(run_dir, 'change').status}")
        assert child.returncode == 0, child.stdout.read()
        assert state.read_run(run_dir).status == "awaiting_approval"
        assert [r.exit for r in usage.read_usage(run_dir, "change")] == ["interrupted", "ok"]
    finally:
        if child.poll() is None:
            _end_group(child.pid)
            child.wait()


def test_a_resume_after_a_resume_of_a_killed_run_recovers_once(killed_mid_fix, engine):
    """The first resume recovers the killed attempt. A second start of the run finds no open attempt, so it writes no
    second recovery and no second interruption."""
    run_dir, _ = killed_mid_fix
    script, writes = chore_script(run_dir, change=[ok(run_dir / "tasks" / "change" / "work" / "change.json")] * 2)
    script["rules"] = []
    eng, _ = engine(script, writes)
    eng.resume("bump-q1w2e")
    eng.resume("bump-q1w2e")
    events = [e.type for e in state.read_events(run_dir)]
    assert events.count("run_resumed") == 1
    assert events.count("task_interrupted") == 1


def test_a_worker_the_killed_engine_left_behind_is_ended_before_a_new_attempt(killed_mid_fix, engine):
    run_dir, leftover = killed_mid_fix
    script, writes = chore_script(run_dir, change=[ok(run_dir / "tasks" / "change" / "work" / "change.json")] * 2)
    script["rules"] = []
    eng, _ = engine(script, writes)
    eng.resume("bump-q1w2e")
    assert [r.exit for r in usage.read_usage(run_dir, "change")] == ["interrupted", "ok"]
    if _alive(leftover):
        raise NotEnded(f"worker process group {leftover} is still running after the resume started attempt 2")
