"""Section 20 (L183): an engine is SIGKILLed while its worker runs, the next tick resumes the run, and the worker the killed
engine left behind is ended. One test runs the whole path with real processes: the engine that dies, the tick, and the
engine the tick starts.

The killed engine is a child process that takes the run's lock and runs `Engine.run` with a worker that starts its own
process group (the left-over worker). The tick's spawn starts a real engine child for the run. Every child is killed in a
`finally`, so a failing test leaves no process running.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from factory_engine import gitops, state
from factory_engine.config import Config
from factory_engine.loadcfg import load_config
from factory_engine.types import Request, Source
from factory_launcher import tick as tick_mod

SRC = Path(tick_mod.__file__).resolve().parents[2]  # factory/: the folder that holds factory_launcher and factory_engine
ENGINE = SRC / "engine"
ENGINE_TESTS = ENGINE / "tests" / "engine"  # `engine_helpers` lives here
RUN = "bump-q1w2e"

# The engine that dies: it runs the fix attempt, whose worker starts a left-over process group, then waits.
KILLED_ENGINE = """
import subprocess, sys, time
from pathlib import Path
sys.path[:0] = [{engine!r}, {engine_tests!r}]
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
            handle.data["proc"] = p  # the engine reads the group id from the handle's process, as the adapters do
        return handle

    def wait(self, handle, timeout_s):
        if handle.task_id == "change":
            print("RUNNING", flush=True)
            time.sleep(600)
        return handle.data["result"]


w = Hang(script, writes=writes)
cfg = Config(machine={machine!r}, repo={{"base_branch": "main", "concurrency": 4, "infra_wait_hours": 6}})
Engine(Path({repo!r}), cfg, workers={{"fake": w}}, command=w, tracker=FakeTracker(), prs=FakePullRequests(),
       clock=FakeClock()).run(["{run}"])
"""

# The engine the tick starts for the run after the kill: the same run, with workers that finish the fix.
TICK_ENGINE = """
import sys
from pathlib import Path
sys.path[:0] = [{engine!r}, {engine_tests!r}]
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
script["rules"] = []  # triage is done before the kill
w = FakeWorkerAdapter(script, writes=writes)
cfg = Config(machine={machine!r}, repo={{"base_branch": "main", "concurrency": 4, "infra_wait_hours": 6}})
Engine(Path({repo!r}), cfg, workers={{"fake": w}}, command=w, tracker=FakeTracker(), prs=FakePullRequests(),
       clock=FakeClock()).run(["{run}"])
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
def run_on_disk(tmp_path, monkeypatch):
    """A git repo with its kit, and a pending run in a factory home. Returns (run folder, repo, machine config, home)."""
    home = tmp_path / "home"
    monkeypatch.setenv("FACTORY_HOME", str(home))
    src = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    (src / "services").mkdir()
    (src / "services" / "api.py").write_text("x = 1\n")
    shutil.copytree(SRC, src / "factory", symlinks=True,
                    ignore=shutil.ignore_patterns(".venv", "__pycache__", "tests", "engine", "launcher", "dashboard"))
    for args in (["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"]):
        subprocess.run(["git", "-C", str(src), *args], check=True)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(bare)], check=True)
    subprocess.run(["git", "-C", str(src), "remote", "add", "origin", str(bare)], check=True)
    subprocess.run(["git", "-C", str(src), "fetch", "-q", "origin"], check=True)
    machine = {"worktree_root": str(tmp_path / "wt"), "worktree_path": "{root}/{repo}/{run_id}"}
    cfg = Config(machine=machine, repo={"base_branch": "main", "concurrency": 4, "infra_wait_hours": 6})
    home.mkdir(parents=True, exist_ok=True)
    source =Source("cli", "acme/report#1", "Bump the lint config", "Bump it.", ["chore"], "alice", [])
    request = Request("cli-1", source, "sha1", "repo", "Bump the lint config", "chore", "explicit", None, [])
    kit_hash = gitops.snapshot_kit(src, "main", state.factory_home())
    ref = state.init_run(state.factory_home(), src, state.repo_key(src, cfg), RUN, request, branch=RUN,
                         worktree=tmp_path / "wt" / src.name / RUN, kit_hash=kit_hash)
    yield ref.run_dir, src, machine, home


def test_a_sigkilled_engine_is_resumed_by_the_tick_and_its_left_over_worker_is_ended(run_on_disk, tmp_path):
    """SIGKILL during a worker, then a real tick: the tick starts a real engine that finishes the fix, and the worker
    group the killed engine left behind is gone before attempt 2 starts."""
    run_dir, repo, machine, home = run_on_disk
    leftover_file = tmp_path / "leftover.pid"
    killed = subprocess.Popen(
        [sys.executable, "-c", KILLED_ENGINE.format(engine=str(ENGINE), engine_tests=str(ENGINE_TESTS), kit=str(SRC),
                                                    run_dir=str(run_dir), repo=str(repo), machine=machine,
                                                    leftover=str(leftover_file), run=RUN)],
        stdout=subprocess.PIPE, text=True, start_new_session=True)
    leftover = None
    children: list[subprocess.Popen] = []
    try:
        assert killed.stdout.readline().strip() == "RUNNING"
        leftover = int(leftover_file.read_text())
        cfg = load_config(None, env={"FACTORY_HOME": str(home)})
        os.kill(killed.pid, signal.SIGSTOP)  # first half of the box: a stopped engine keeps its lock past the old 60 s
        later = datetime.now(timezone.utc) + timedelta(minutes=10)
        for _ in range(2):
            idle = tick_mod.tick(cfg, repos=[], home=home, spawn=lambda r, rid: pytest.fail("a second engine started"),
                                 now=later)
            assert idle.started == [] and idle.resumed == []
        assert state.lock_status(run_dir) == "live"
        os.kill(killed.pid, signal.SIGKILL)  # second half: SIGKILL ends a stopped process too
        killed.wait()
        assert state.lock_status(run_dir) == "stale"
        assert _alive(leftover)  # the worker outlived its engine, as it does after a real kill

        spawned: list[str] = []

        def spawn(repo_path, run_id):
            spawned.append(run_id)
            child = subprocess.Popen(
                [sys.executable, "-c", TICK_ENGINE.format(engine=str(ENGINE), engine_tests=str(ENGINE_TESTS),
                                                          kit=str(SRC), run_dir=str(run_dir), repo=str(repo),
                                                          machine=machine, run=run_id)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
            children.append(child)
            return child.pid

        report = tick_mod.tick(cfg, repos=[], home=home, spawn=spawn)
        assert report.resumed == [RUN] and spawned == [RUN]

        child = children[0]
        try:
            child.wait(timeout=60)
        except subprocess.TimeoutExpired:
            raise AssertionError("the engine the tick started has not returned after 60 s; run is "
                                 f"{state.read_run(run_dir).status}") from None
        assert child.returncode == 0, child.stdout.read()
        assert state.read_run(run_dir).status == "awaiting_approval"  # the fix finished; the run waits at merge review
        assert _exits(run_dir, "change") == ["interrupted", "ok"]  # attempt 1 was killed, attempt 2 finished
        assert not _alive(leftover), "the left-over worker group was not ended before the resumed attempt"
    finally:
        if killed.poll() is None:
            try:
                os.kill(killed.pid, signal.SIGCONT)  # a stopped process acts on the kill only after SIGCONT
            except ProcessLookupError:
                pass
        for child in children:
            if child.poll() is None:
                _end_group(child.pid)
                child.wait()
        if killed.poll() is None:
            killed.kill()
            killed.wait()
        _end_group(leftover)


def _exits(run_dir: Path, task_id: str) -> list[str]:
    from factory_engine import usage
    return [r.exit for r in usage.read_usage(run_dir, task_id)]
