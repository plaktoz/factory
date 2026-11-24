"""Section 20 integration tests that need real processes: overlapping ticks, and an engine stopped with SIGSTOP.

Each test starts a real child and kills it in a `finally`, so a failing test leaves nothing running. The tick's `spawn`
is a recorder in the test's own process, so no engine starts; what is tested is the tick's decision and the locks.
"""

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from factory_engine import state
from factory_engine.loadcfg import load_config
from factory_launcher import tick as tick_mod

SRC = Path(tick_mod.__file__).resolve().parents[2]  # the folder that holds factory_launcher and factory_engine
PATHS = [str(SRC / "launcher"), str(SRC / "engine")]


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(h))
    return h


def _run(home: Path, run_id: str, repo: Path, status: str) -> Path:
    run_dir = home / "runs" / "local" / "repo" / run_id
    run_dir.mkdir(parents=True)
    run = {"schema_version": 1, "run_id": run_id, "repo": repo.name, "repo_key": "local/repo", "repo_path": str(repo),
           "status": status, "stage": None, "stages": [], "loops": {}, "workflow": "chore", "attention": None}
    (run_dir / "run.json").write_text(json.dumps(run))
    (run_dir / "events.jsonl").write_text("")
    return run_dir


def _stop_child(child: subprocess.Popen) -> None:
    """End a child whatever state it is in. SIGCONT first so a stopped child can act on the kill."""
    if child.poll() is None:
        try:
            os.kill(child.pid, signal.SIGCONT)
        except ProcessLookupError:
            pass
        child.kill()
    child.wait()


# A tick whose spawn stands still until the test releases it, so the tick lock is held for as long as the test needs.
SLOW_TICK = """
import json, sys
sys.path[:0] = {paths!r}
from pathlib import Path
from factory_engine.loadcfg import load_config
from factory_launcher import tick

home = Path({home!r})
spawned = []


def spawn(repo, run_id):
    spawned.append(run_id)
    print("SPAWNING", flush=True)
    sys.stdin.readline()  # the test writes a line to let this tick finish
    return 1


report = tick.tick(load_config(None, env={{"FACTORY_HOME": str(home)}}), repos=[], home=home, spawn=spawn)
print(json.dumps({{"spawned": spawned, "started": report.started, "skipped_tick": report.skipped_tick}}), flush=True)
"""


def test_a_tick_that_overlaps_a_running_tick_exits_at_once_and_the_run_starts_once(home, tmp_path):
    """Two real ticks at the same moment: the first is inside its spawn and holds the tick lock; the second returns
    `skipped_tick` and starts nothing; the run is started exactly once, by the first."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(home, "bump-q1w2e", repo, "pending")
    first = subprocess.Popen([sys.executable, "-c", SLOW_TICK.format(paths=PATHS, home=str(home))],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert first.stdout.readline().strip() == "SPAWNING"
        started: list[str] = []
        second = tick_mod.tick(load_config(None, env={"FACTORY_HOME": str(home)}), repos=[], home=home,
                               spawn=lambda r, rid: started.append(rid) or 1)
        assert second.skipped_tick is True and second.started == [] and started == []
        first.stdin.write("go\n")
        first.stdin.flush()
        done = json.loads(first.stdout.readline())
        assert done["spawned"] == ["bump-q1w2e"] and done["started"] == ["bump-q1w2e"]
        assert done["skipped_tick"] is False
    finally:
        _stop_child(first)


# An engine: takes the run's lock, as `Engine.tick` does, then holds it until it is killed.
HOLDER = """
import sys, time
sys.path[:0] = {paths!r}
from pathlib import Path
from factory_engine.lock import acquire_lock
acquire_lock(Path({run_dir!r}), "engine")
print("HELD", flush=True)
time.sleep(600)
"""


@pytest.mark.skipif(sys.platform == "win32", reason="SIGSTOP and SIGCONT do not exist on Windows")
def test_a_tick_starts_no_second_engine_for_a_stopped_engine_and_resumes_it_once_it_is_killed(home, tmp_path):
    """An engine stopped with SIGSTOP keeps its kernel lock. Its heartbeat is set to ten minutes before the tick, past
    the old 60 s limit, because the lock is not a heartbeat timeout. Ticks find the run live and start nothing. After
    SIGKILL the lock is gone and the next tick resumes the run."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_dir = _run(home, "bump-q1w2e", repo, "running")
    cfg = load_config(None, env={"FACTORY_HOME": str(home)})
    now = datetime.now(timezone.utc) + timedelta(minutes=10)
    engine = subprocess.Popen([sys.executable, "-c", HOLDER.format(paths=PATHS, run_dir=str(run_dir))],
                              stdout=subprocess.PIPE, text=True)
    spawned: list[str] = []

    def spawn(repo_path, run_id):
        spawned.append(run_id)
        return 1

    try:
        assert engine.stdout.readline().strip() == "HELD"
        os.kill(engine.pid, signal.SIGSTOP)
        lock_file = run_dir / "lock"
        holder = json.loads(lock_file.read_text())
        holder["heartbeat"] = time.time() - 600  # the engine cannot beat while stopped
        lock_file.write_text(json.dumps(holder))
        assert state.lock_status(run_dir) == "live"

        for _ in range(2):  # more than one tick while it stays stopped: a `running` run with a live lock is left alone
            report = tick_mod.tick(cfg, repos=[], home=home, spawn=spawn, now=now)
            assert report.started == [] and report.resumed == [] and spawned == []
        assert state.lock_status(run_dir) == "live"

        engine.kill()  # SIGKILL ends a stopped process too
        engine.wait()
        assert state.lock_status(run_dir) == "stale"
        starts: list[str] = []
        report = tick_mod.tick(cfg, repos=[], home=home, spawn=lambda r, rid: starts.append(rid) or 1, now=now)
        assert report.resumed == ["bump-q1w2e"] and starts == ["bump-q1w2e"]
    finally:
        _stop_child(engine)
