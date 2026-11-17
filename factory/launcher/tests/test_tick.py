"""The machine tick (module 6, "Scheduled ticks"): one action per run, a single tick at a time, and tick.json written.

The spawn is a recorder, so a test sees which engines a tick would start and no process starts.
"""

import fcntl
import json
import os
from pathlib import Path

import pytest

from factory_engine import state
from factory_engine.clock import FakeClock
from factory_engine.config import Config
from factory_engine.loadcfg import load_config
from factory_engine.lock import acquire_lock, release
from factory_launcher import tick as tick_mod


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(h))
    return h


def _run(home: Path, run_id: str, repo: Path, status: str, *, key="local/repo") -> Path:
    """A run folder with a run.json of the given status, the way the engine leaves one."""
    run_dir = home / "runs" / key / run_id
    run_dir.mkdir(parents=True)
    run = {"schema_version": 1, "run_id": run_id, "repo": repo.name, "repo_key": key, "repo_path": str(repo),
           "status": status, "stage": None, "stages": [], "loops": {}, "workflow": "chore", "attention": None}
    (run_dir / "run.json").write_text(json.dumps(run))
    (run_dir / "events.jsonl").write_text("")
    return run_dir


def _repo(tmp_path: Path, name="repo") -> Path:
    p = tmp_path / name
    p.mkdir()
    return p


# ---- the table: one action per run ------------------------------------------------------------------------------

@pytest.mark.parametrize("status,lock,repo_exists,answered,expected", [
    ("pending", "free", True, False, tick_mod.START),
    ("running", "stale", True, False, tick_mod.RESUME),
    ("running", "live", True, False, tick_mod.NOTHING),
    ("awaiting_approval", "free", True, True, tick_mod.START),
    ("awaiting_approval", "free", True, False, tick_mod.NOTHING),
    ("retrying", "free", True, False, tick_mod.START),
    ("blocked", "free", True, False, tick_mod.NOTHING),
    ("done", "free", True, False, tick_mod.NOTHING),
    ("pending", "free", False, False, tick_mod.MISSING),
])
def test_each_status_and_lock_gets_the_action_module_6_gives(status, lock, repo_exists, answered, expected):
    assert tick_mod.decide(status, lock, repo_exists, answered=answered) == expected


# ---- a tick: start, resume, skip ----------------------------------------------------------------------------------

def test_a_tick_starts_an_engine_for_a_pending_run_and_writes_tick_json(home, tmp_path):
    repo = _repo(tmp_path)
    _run(home, "bump-q1w2e", repo, "pending")
    started: list[str] = []
    report = tick_mod.tick(load_config(None, env={"FACTORY_HOME": str(home)}), repos=[],
                           home=home, spawn=lambda r, rid: started.append(rid) or 1)
    assert started == ["bump-q1w2e"] and report.started == ["bump-q1w2e"]
    doc = json.loads((home / "tick.json").read_text())
    assert doc["last_tick"] and doc["result"]["started"] == ["bump-q1w2e"]


def test_a_tick_leaves_a_running_run_with_a_live_engine_alone(home, tmp_path):
    repo = _repo(tmp_path)
    run_dir = _run(home, "bump-q1w2e", repo, "running")
    held = acquire_lock(run_dir, "engine")
    started: list[str] = []
    try:
        report = tick_mod.tick(load_config(None, env={"FACTORY_HOME": str(home)}), repos=[],
                               home=home, spawn=lambda r, rid: started.append(rid) or 1)
    finally:
        release(held)
    assert started == [] and report.started == [] and report.resumed == []


def test_a_tick_resumes_a_running_run_whose_engine_died(home, tmp_path):
    repo = _repo(tmp_path)
    _run(home, "bump-q1w2e", repo, "running")
    started: list[str] = []
    report = tick_mod.tick(load_config(None, env={"FACTORY_HOME": str(home)}), repos=[],
                           home=home, spawn=lambda r, rid: started.append(rid) or 1)
    assert started == ["bump-q1w2e"] and report.resumed == ["bump-q1w2e"]


def test_a_run_whose_repo_is_gone_is_reported_and_starts_nothing(home, tmp_path):
    gone = tmp_path / "moved-away"
    _run(home, "bump-q1w2e", gone, "pending")
    started: list[str] = []
    report = tick_mod.tick(load_config(None, env={"FACTORY_HOME": str(home)}), repos=[],
                           home=home, spawn=lambda r, rid: started.append(rid) or 1)
    assert started == [] and report.repo_missing == ["bump-q1w2e"]


def test_a_tick_that_finds_another_tick_holding_the_lock_exits_at_once(home, tmp_path):
    """Two ticks fired together: the first holds the machine tick lock, the second returns skipped and starts nothing."""
    repo = _repo(tmp_path)
    _run(home, "bump-q1w2e", repo, "pending")
    fd = os.open(str(home / tick_mod.TICK_LOCK), os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    started: list[str] = []
    try:
        report = tick_mod.tick(load_config(None, env={"FACTORY_HOME": str(home)}), repos=[],
                               home=home, spawn=lambda r, rid: started.append(rid) or 1)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert report.skipped_tick is True and started == []
    assert "tick_skipped" in (home / "logs" / "tick.log").read_text()


def test_two_ticks_in_a_row_do_not_start_a_run_twice(home, tmp_path):
    """The second tick finds the run already held by the engine the first tick started, so it starts nothing."""
    repo = _repo(tmp_path)
    run_dir = _run(home, "bump-q1w2e", repo, "pending")
    cfg = load_config(None, env={"FACTORY_HOME": str(home)})
    started: list[str] = []

    def spawn(repo_path, rid):
        started.append(rid)
        held = acquire_lock(run_dir, "engine")  # the engine the first tick started takes the run's lock
        spawn.held = held
        return 1

    tick_mod.tick(cfg, repos=[], home=home, spawn=spawn)
    run_dir_status = state.lock_status(run_dir)
    second = tick_mod.tick(cfg, repos=[], home=home, spawn=lambda r, rid: started.append(rid) or 1)
    release(spawn.held)
    assert started == ["bump-q1w2e"] and run_dir_status == "live"
    assert second.started == []


def test_a_tick_syncs_each_repo_with_its_own_settings(home, tmp_path, monkeypatch):
    """The machine config comes from load_config(None) with no repo part; each repo syncs through its own."""
    repo = _repo(tmp_path)
    seen: list[Path] = []
    monkeypatch.setattr(tick_mod.api, "sync", lambda r: seen.append(Path(r)) or type("R", (), {"created": []})())
    cfg = load_config(None, env={"FACTORY_HOME": str(home)})
    assert cfg.repo is None
    tick_mod.tick(cfg, repos=[repo], home=home, spawn=lambda r, rid: 1)
    assert seen == [repo]


def test_the_tick_report_names_the_steps_the_engine_cannot_do_yet(home, tmp_path):
    report = tick_mod.tick(load_config(None, env={"FACTORY_HOME": str(home)}), repos=[], home=home,
                           spawn=lambda r, rid: 1)
    assert any("pull request" in u for u in report.unsupported)
