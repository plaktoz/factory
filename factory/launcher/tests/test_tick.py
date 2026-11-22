"""The machine tick (module 6, "Scheduled ticks"): one action per run, a single tick at a time, and tick.json written.

The spawn is a recorder, so a test sees which engines a tick would start and no process starts.
"""

import json
import os
from pathlib import Path

import pytest

from factory_engine import filelock, state
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
    ("awaiting_approval", "live", True, False, tick_mod.NOTHING),
    ("retrying", "free", True, False, tick_mod.START),
    ("blocked", "free", True, False, tick_mod.NOTHING),
    ("done", "free", True, False, tick_mod.NOTHING),
    ("pending", "free", False, False, tick_mod.MISSING),
])
def test_each_status_and_lock_gets_the_action_module_6_gives(status, lock, repo_exists, answered, expected):
    assert tick_mod.decide(status, lock, repo_exists, answered=answered) == expected


@pytest.mark.parametrize("status,lock,expected", [
    ("awaiting_approval", "free", tick_mod.START),
    ("awaiting_approval", "live", tick_mod.NOTHING),
    ("running", "free", tick_mod.NOTHING),
    ("done", "free", tick_mod.NOTHING),
])
def test_a_changed_pull_request_starts_an_engine_only_for_a_waiting_run_with_no_live_lock(status, lock, expected):
    assert tick_mod.decide(status, lock, True, pr_changed=True) == expected


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
    assert filelock.try_lock(fd)
    started: list[str] = []
    try:
        report = tick_mod.tick(load_config(None, env={"FACTORY_HOME": str(home)}), repos=[],
                               home=home, spawn=lambda r, rid: started.append(rid) or 1)
    finally:
        filelock.unlock(fd)
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


# ---- a run waiting on its pull request (module 6 step 3, module 13 watch_pr) ---------------------------------------

@pytest.fixture
def waiting(home, tmp_path):
    """A run parked at its merge review, with a pull request on a FakePullRequests the tick reads."""
    from factory_engine import gitops
    from factory_engine.fake_prs import FakePullRequests
    from factory_engine.types import PrRef, Request, Source

    repo = _repo(tmp_path)
    cfg = Config(machine={}, repo={"base_branch": "main"})
    src = Source("cli", "acme/report#1", "Bump", "Bump it.", ["chore"], "alice", [])
    request = Request("cli-1", src, "sha1", "repo", "Bump", "chore", "explicit", None, [])
    ref = state.init_run(home, repo, state.repo_key(repo, cfg), "bump-q1w2e", request, branch="bump-q1w2e",
                         worktree=tmp_path / "wt", kit_hash="0" * 12)
    prs = FakePullRequests()
    body = tmp_path / "body.md"
    body.write_text("body")
    pr = prs.create(tmp_path, base="main", head="bump-q1w2e", title="Bump", body_file=body, labels=[])
    run = state.read_run(ref.run_dir)
    run.status, run.pr, run.workflow = "awaiting_approval", PrRef(**pr.__dict__), "chore"
    lock = acquire_lock(ref.run_dir, "test")
    state.write_run(ref.run_dir, run, lock=lock)
    release(lock)
    return ref, prs, pr


def _tick(home, prs, spawned):
    return tick_mod.tick(load_config(None, env={"FACTORY_HOME": str(home)}), repos=[], home=home,
                         spawn=lambda r, rid: spawned.append(rid) or 1, prs_for=lambda repo: prs)


def test_a_tick_leaves_a_run_whose_pull_request_is_open_with_ci_pending(waiting, home):
    ref, prs, pr = waiting
    spawned: list[str] = []
    prs.set_ci(pr, "pending")
    report = _tick(home, prs, spawned)
    assert spawned == [] and report.started == []


def test_the_first_green_ci_starts_an_engine_so_it_can_check_the_merge_rules_again(waiting, home):
    ref, prs, pr = waiting
    prs.set_ci(pr, "green")
    spawned: list[str] = []
    report = _tick(home, prs, spawned)
    assert spawned == ["bump-q1w2e"] and report.started == ["bump-q1w2e"]


def test_green_ci_already_checked_starts_no_engine(waiting, home):
    ref, prs, pr = waiting
    state.append_event(ref.run_dir, "merge_evaluated", auto=False, reason="chore is not in the auto workflows", ci="green")
    prs.set_ci(pr, "green")
    spawned: list[str] = []
    report = _tick(home, prs, spawned)
    assert spawned == [] and report.started == []


@pytest.mark.parametrize("change", ["merge", "close", "red"])
def test_a_tick_starts_an_engine_for_a_run_whose_pull_request_merged_closed_or_went_red(waiting, home, change):
    ref, prs, pr = waiting
    {"merge": prs.human_merge, "close": prs.close, "red": lambda p: prs.set_ci(p, "red", "lint: FAILURE")}[change](pr)
    spawned: list[str] = []
    report = _tick(home, prs, spawned)
    assert spawned == ["bump-q1w2e"] and report.started == ["bump-q1w2e"]


def test_a_tick_writes_no_run_state_when_it_reads_a_pull_request(waiting, home):
    ref, prs, pr = waiting
    prs.human_merge(pr)
    before = (ref.run_dir / "run.json").read_text()
    _tick(home, prs, [])
    assert (ref.run_dir / "run.json").read_text() == before
    assert state.read_run(ref.run_dir).status == "awaiting_approval"


def test_a_tick_that_cannot_read_github_reports_it_and_starts_nothing(waiting, home):
    from factory_engine.errors import FactoryError
    ref, prs, pr = waiting
    prs.fail_next = FactoryError("git.network", "gh is unreachable")
    spawned: list[str] = []
    report = _tick(home, prs, spawned)
    assert spawned == [] and any("gh is unreachable" in e for e in report.errors)


def test_a_tick_does_not_read_a_pull_request_while_an_engine_holds_the_run(waiting, home):
    ref, prs, pr = waiting
    prs.human_merge(pr)
    lock = acquire_lock(ref.run_dir, "live")
    try:
        spawned: list[str] = []
        _tick(home, prs, spawned)
        assert spawned == [] and "state" not in prs.calls
    finally:
        release(lock)


# ---- reminders for a run that waits for a person (module 11, owner decision D2, 2026-11-22) ------------------------

@pytest.fixture
def stopped(home, tmp_path):
    """A GitHub-issue run parked at an approval stop with no engine, opened at 2026-11-22T10:00 UTC."""
    from factory_engine.types import AttentionItem, Request, Source

    repo = _repo(tmp_path)
    cfg = Config(machine={}, repo={"base_branch": "main"})
    src = Source("github", "acme/report#1", "Bump", "Bump it.", ["chore"], "alice", [])
    request = Request("gh-1", src, "sha1", "repo", "Bump", "chore", "explicit", None, [])
    ref = state.init_run(home, repo, state.repo_key(repo, cfg), "bump-q1w2e", request, branch="bump-q1w2e",
                         worktree=tmp_path / "wt", kit_hash="0" * 12)
    run = state.read_run(ref.run_dir)
    run.status, run.stage, run.workflow = "awaiting_approval", "implement", "chore"
    run.attention = AttentionItem(kind="approval", run_id="bump-q1w2e", stage="implement", since="2026-11-22T10:00:00+00:00",
                                  summary="Approve implement", page=None, command="factory decide bump-q1w2e D1=approve")
    lock = acquire_lock(ref.run_dir, "test")
    state.write_run(ref.run_dir, run, lock=lock)
    release(lock)
    return ref


def _tick_at(home, tracker, when, started=None, monkeypatch=None):
    from datetime import datetime, timezone
    at = datetime.fromisoformat(when).astimezone(timezone.utc)
    if monkeypatch is not None:                                      # events are stamped with the tick's own time
        monkeypatch.setattr(state, "_now", lambda: at.isoformat(timespec="seconds"))
    return tick_mod.tick(load_config(None, env={"FACTORY_HOME": str(home)}), repos=[], home=home,
                         spawn=lambda r, rid: (started if started is not None else []).append(rid) or 1,
                         now=at, tracker_for=lambda repo: tracker)


def _told_at(run_dir, when):
    """The engine's first notice of the stop, as `notify` leaves it."""
    state.append_event(run_dir, "attention_notified", kind="approval", stage="implement", sent=["tracker"], failed={})
    lines = (run_dir / "events.jsonl").read_text().splitlines()
    last = json.loads(lines[-1])
    last["ts"] = when
    lines[-1] = json.dumps(last)
    (run_dir / "events.jsonl").write_text("\n".join(lines) + "\n")


def test_a_tick_sends_one_reminder_a_day_while_a_run_waits_and_starts_no_engine(stopped, home, monkeypatch):
    from factory_engine.adapters.tracker.fake import FakeTracker
    tracker, started = FakeTracker(), []
    _told_at(stopped.run_dir, "2026-11-22T10:00:00+00:00")
    tick = lambda when: _tick_at(home, tracker, when, started, monkeypatch)  # noqa: E731
    for when in ("2026-11-22T11:00:00+00:00", "2026-11-22T20:00:00+00:00", "2026-11-23T09:59:00+00:00"):
        assert tick(when).reminded == []                                  # under 24 hours since the notice
    assert tracker.statuses == []
    assert tick("2026-11-23T10:00:00+00:00").reminded == ["bump-q1w2e"]
    assert [c.status for c in tracker.statuses] == ["factory:needs-human"]
    assert "Reminder: run `bump-q1w2e` still needs you: Approve implement" in tracker.statuses[0].comment
    assert "@alice" in tracker.statuses[0].comment
    assert tick("2026-11-23T11:00:00+00:00").reminded == [] and len(tracker.statuses) == 1
    assert tick("2026-11-24T10:00:00+00:00").reminded == ["bump-q1w2e"] and len(tracker.statuses) == 2
    assert started == []


def test_a_run_that_is_not_waiting_gets_no_reminder(stopped, home, monkeypatch):
    from factory_engine.adapters.tracker.fake import FakeTracker
    tracker = FakeTracker()
    _told_at(stopped.run_dir, "2026-11-20T10:00:00+00:00")
    run = state.read_run(stopped.run_dir)
    run.status, run.attention = "running", None
    lock = acquire_lock(stopped.run_dir, "test")
    state.write_run(stopped.run_dir, run, lock=lock)
    release(lock)
    assert _tick_at(home, tracker, "2026-11-23T10:00:00+00:00", monkeypatch=monkeypatch).reminded == []
    assert tracker.statuses == []


def test_reminders_off_and_a_failed_tracker_are_both_quiet_for_the_tick(stopped, home, monkeypatch):
    from factory_engine import notify
    from factory_engine.adapters.tracker.fake import FakeTracker

    monkeypatch.setattr(notify.time, "sleep", lambda s: None)

    class Down(FakeTracker):
        def set_status(self, ref, status, *, comment=None, link=None):
            raise OSError("gh is down")

    _told_at(stopped.run_dir, "2026-11-22T10:00:00+00:00")
    report = _tick_at(home, Down(), "2026-11-23T10:00:00+00:00", monkeypatch=monkeypatch)
    assert report.skipped_tick is False and any("could not tell tracker" in e for e in report.errors)


def test_a_tick_that_dies_holding_the_lock_releases_it_for_the_next_tick(home):
    """Module 6 step 1: the tick lock is an OS file lock, so a killed tick frees it at once. A real process holds the lock
    and is killed with SIGKILL; a second tick then gets the lock. A lock file left behind would fail this test."""
    import subprocess
    import sys
    import textwrap

    src = Path(tick_mod.__file__).resolve().parents[2]  # the folder that holds factory_launcher and factory_engine
    child = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import sys, time
        sys.path[:0] = {[str(src / "launcher"), str(src / "engine")]!r}
        from pathlib import Path
        from factory_launcher import tick
        assert tick._take_tick_lock(Path({str(home)!r})) is not None
        print("held", flush=True)
        time.sleep(60)
    """)], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "held"
        assert tick_mod._take_tick_lock(home) is None
    finally:
        child.kill()
        child.wait()
    lock = tick_mod._take_tick_lock(home)
    assert lock is not None
    tick_mod._release_tick_lock(lock)
