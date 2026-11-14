"""Module 17 acceptance criteria. Git runs for real on temp repos; the clock is a FakeClock."""

import json
import shutil
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from factory_engine import gitops, housekeeping, state
from factory_engine.housekeeping import apply, cleanup_after_join, cleanup_after_merge, plan

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import KEY, branch_exists, dirty, days_ago, make_run, write_repo_config  # noqa: E402


def worktree_for(cfg, repo, run_id):
    return gitops.create_run_worktree(repo, cfg, run_id, base="main", detached=False)


def task_worktree(cfg, repo, run_id, task_id):
    return gitops.create_task_worktree(repo, cfg, run_id, task_id)


def items_of(p, kind):
    return [i for i in p.items if i.kind == kind]


def skipped_paths(report_or_plan):
    return {str(s.path): s.reason for s in report_or_plan.skipped}


# --- criterion 1: plan lists only ended runs past retention ---

def test_only_ended_runs_past_retention_are_planned(home, repo, cfg, clock):
    wt_old = worktree_for(cfg, repo, "old")
    wt_new = worktree_for(cfg, repo, "new")
    wt_live = worktree_for(cfg, repo, "live")
    wt_block = worktree_for(cfg, repo, "block")
    make_run(home, repo, "old", status="done", worktree=wt_old, ended=days_ago(clock, 8))
    make_run(home, repo, "new", status="done", worktree=wt_new, ended=days_ago(clock, 3))
    make_run(home, repo, "live", status="running", worktree=wt_live, ended=days_ago(clock, 90))
    make_run(home, repo, "block", status="blocked", worktree=wt_block, ended=days_ago(clock, 90))

    p = plan(home, cfg, now=clock.now())

    archived = {i.run_id for i in items_of(p, "archive")}
    assert archived == {"old"}
    touched = {i.run_id for i in p.items}
    assert "live" not in touched and "block" not in touched


def test_an_engine_holding_the_lock_keeps_its_ended_run(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "held")
    run_dir = make_run(home, repo, "held", status="done", worktree=wt, ended=days_ago(clock, 30))
    lock = state.acquire_lock(run_dir, "another-engine")
    try:
        p = plan(home, cfg, now=clock.now())
    finally:
        state.release(lock)
    assert not items_of(p, "archive")
    assert any(s.run_id == "held" and "lock" in s.reason for s in p.skipped)


# --- criteria 2 and 3: dirty worktrees and cleanup_check ---

def test_a_dirty_worktree_with_no_check_is_skipped_by_the_plan(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "dirty")
    dirty(wt)
    make_run(home, repo, "dirty", status="done", worktree=wt, ended=days_ago(clock, 8))

    p = plan(home, cfg, now=clock.now())
    report = apply(p)

    assert str(wt) in skipped_paths(p)
    assert wt.exists(), "a dirty worktree must not be removed"
    assert (wt / "wip.txt").read_text() == "uncommitted\n"
    assert str(wt) in skipped_paths(report)


@pytest.mark.parametrize("check_yaml", ['cleanup_check: ["false"]',
                                        'cleanup_check: ["definitely-not-a-command-xyz"]'])
def test_a_dirty_worktree_whose_check_fails_is_kept_and_reported(home, repo, cfg, clock, check_yaml):
    write_repo_config(repo, check_yaml + "\n")
    wt = worktree_for(cfg, repo, "dirty")
    dirty(wt)
    make_run(home, repo, "dirty", status="done", worktree=wt, ended=days_ago(clock, 8))

    report = apply(plan(home, cfg, now=clock.now()))

    assert wt.exists(), "a dirty worktree must not be removed"
    assert str(wt) in skipped_paths(report)
    assert (wt / "wip.txt").read_text() == "uncommitted\n"


def test_a_check_that_times_out_keeps_the_dirty_worktree(home, repo, cfg, clock, monkeypatch):
    monkeypatch.setattr(housekeeping, "CHECK_TIMEOUT_S", 1)
    write_repo_config(repo, 'cleanup_check: ["sleep", "5"]\n')
    wt = worktree_for(cfg, repo, "slow")
    dirty(wt)
    make_run(home, repo, "slow", status="done", worktree=wt, ended=days_ago(clock, 8))

    report = apply(plan(home, cfg, now=clock.now()))

    assert wt.exists()
    reason = next(s for s in report.skipped if s.path == wt)
    assert "timed out" in reason.detail


def test_a_dirty_worktree_is_removed_when_the_check_exits_zero_in_it(home, repo, cfg, clock, tmp_path):
    marker = tmp_path / "check-ran-in.txt"
    write_repo_config(repo, f'cleanup_check: ["sh", "-c", "test -f wip.txt && pwd > {marker}"]\n')
    wt = worktree_for(cfg, repo, "checked")
    dirty(wt)
    make_run(home, repo, "checked", status="done", worktree=wt, ended=days_ago(clock, 8))

    report = apply(plan(home, cfg, now=clock.now()))

    assert Path(marker.read_text().strip()).resolve() == wt.resolve(), "the check ran in the worktree"
    assert str(wt) in report.removed
    assert not wt.exists()
    assert not branch_exists(repo, "checked")


# --- criterion 4: a skipped worktree is reported by every later gc ---

def test_a_skipped_worktree_is_reported_until_removed_and_its_run_is_archived(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "stuck")
    dirty(wt)
    run_dir = make_run(home, repo, "stuck", status="done", worktree=wt, ended=days_ago(clock, 8))

    first = apply(plan(home, cfg, now=clock.now()))
    assert not run_dir.exists(), "the run is archived even though its worktree stays"
    assert (home / "archive").is_dir()
    assert str(wt) in skipped_paths(first)

    second = plan(home, cfg, now=clock.now())
    assert str(wt) in skipped_paths(second), "a later gc reports the same worktree"

    shutil.rmtree(wt)
    gitops.git(repo, "worktree", "prune")
    later = plan(home, cfg, now=clock.now())
    assert str(wt) not in skipped_paths(later)


# --- criterion 5: an interrupted archive leaves the run folder intact ---

def test_an_interrupted_archive_leaves_the_run_folder_intact(home, repo, cfg, clock, monkeypatch):
    wt = worktree_for(cfg, repo, "cut")
    run_dir = make_run(home, repo, "cut", status="done", worktree=wt, ended=days_ago(clock, 8))
    before = sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file())

    def interrupted(run_dir_arg, zip_path):
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.with_name(zip_path.name + ".tmp").write_bytes(b"PK partial")
        raise OSError("disk full")

    monkeypatch.setattr(housekeeping, "_write_archive", interrupted)
    report = apply(plan(home, cfg, now=clock.now()))

    assert run_dir.is_dir()
    after = sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file())
    assert after == before
    assert not list((home / "archive").rglob("*.zip")), "no zip is left at the final path"
    assert not (home / "history.jsonl").exists()
    assert report.failed and "disk full" in report.failed[0].message


# --- criterion 6: join and merge cleanups ---

def test_clean_task_worktree_and_branch_are_gone_right_after_the_join(home, repo, cfg, clock):
    run_wt = worktree_for(cfg, repo, "joined")
    task_wt = task_worktree(cfg, repo, "joined", "backend")
    run_dir = make_run(home, repo, "joined", status="running", worktree=run_wt,
                       tasks=[("backend", "done", task_wt)])
    run = state.read_run(run_dir)

    cleanup_after_join(repo, cfg, run, ["backend"])

    assert not task_wt.exists()
    assert not branch_exists(repo, "joined--backend")
    assert run_wt.exists(), "the run worktree is not touched by a join"


def test_a_dirty_task_worktree_after_join_stays_and_is_reported_by_gc(home, repo, cfg, clock):
    run_wt = worktree_for(cfg, repo, "joined2")
    task_wt = task_worktree(cfg, repo, "joined2", "backend")
    dirty(task_wt)
    run_dir = make_run(home, repo, "joined2", status="running", worktree=run_wt,
                       tasks=[("backend", "done", task_wt)])
    run = state.read_run(run_dir)

    cleanup_after_join(repo, cfg, run, ["backend"])
    p = plan(home, cfg, now=clock.now())

    assert task_wt.exists()
    assert str(task_wt) in skipped_paths(p)
    assert "joined" in next(s.reason for s in p.skipped if s.path == task_wt)


def test_the_run_worktree_and_branch_are_gone_right_after_merge(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "merged")
    run_dir = make_run(home, repo, "merged", status="done", worktree=wt)
    run = state.read_run(run_dir)

    cleanup_after_merge(repo, cfg, run)

    assert not wt.exists()
    assert not branch_exists(repo, "merged")


def test_a_dirty_run_worktree_after_merge_stays_when_the_check_is_unset(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "merged-dirty")
    dirty(wt)
    run_dir = make_run(home, repo, "merged-dirty", status="done", worktree=wt)
    cleanup_after_merge(repo, cfg, state.read_run(run_dir))
    assert wt.exists()
    assert branch_exists(repo, "merged-dirty")


# --- criterion 7: every archived run keeps one history line ---

def test_every_archived_run_keeps_one_history_line(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "hist")
    make_run(home, repo, "hist", status="done", worktree=wt, ended=days_ago(clock, 8))
    apply(plan(home, cfg, now=clock.now()))
    apply(plan(home, cfg, now=clock.now()))  # a second gc must not add a line

    lines = [json.loads(l) for l in (home / "history.jsonl").read_text().splitlines()]
    assert [r["run_id"] for r in lines] == ["hist"]
    assert lines[0]["status"] == "done"
    assert lines[0]["repo_key"] == KEY
    assert lines[0]["ended"]


# --- criterion 8: kit snapshots ---

def test_a_kit_used_by_an_unarchived_run_is_kept_and_an_unused_one_is_deleted(home, repo, cfg, clock):
    worktree_for(cfg, repo, "active")
    make_run(home, repo, "active", status="running", worktree=repo, kit="kit-used")
    make_run(home, repo, "old", status="done", worktree=repo, kit="kit-old", ended=days_ago(clock, 8))
    for name in ("kit-used", "kit-old", "kit-unused"):
        (home / "kits" / name).mkdir(parents=True)
        (home / "kits" / name / "factory").mkdir()

    apply(plan(home, cfg, now=clock.now()))

    assert (home / "kits" / "kit-used").is_dir()
    assert not (home / "kits" / "kit-old").exists(), "its only run was archived"
    assert not (home / "kits" / "kit-unused").exists()


# --- criterion 9: orphans reported both ways ---

def test_a_worktree_marker_that_points_to_no_run_is_an_orphan(home, repo, cfg, clock):
    ghost = cfg.machine["worktree_root"] + "/repo/ghost"
    Path(ghost).mkdir(parents=True)
    (Path(ghost) / ".factory-run.json").write_text(json.dumps(
        {"run_id": "ghost", "repo_key": KEY, "run_dir": str(home / "runs" / KEY / "ghost")}))

    p = plan(home, cfg, now=clock.now())

    assert [(o.path, o.run_id) for o in p.orphans] == [(Path(ghost), "ghost")]


def test_a_run_whose_recorded_worktree_is_gone_is_an_orphan(home, repo, cfg, clock):
    make_run(home, repo, "missing-wt", status="running", worktree=Path(cfg.machine["worktree_root"]) / "gone")
    p = plan(home, cfg, now=clock.now())
    assert any(o.run_id == "missing-wt" and "worktree" in o.reason for o in p.orphans)


def test_a_run_whose_repo_is_gone_is_an_orphan(home, repo, cfg, clock, tmp_path):
    gone = tmp_path / "vanished"
    make_run(home, repo, "no-repo", status="running", worktree=repo, repo_path=gone)
    p = plan(home, cfg, now=clock.now())
    assert any(o.run_id == "no-repo" and "repo" in o.reason for o in p.orphans)


# --- criterion 10: a run whose repo is gone ---

def test_a_run_whose_repo_is_gone_is_archived_after_keep_failed_days(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "orphaned")
    shutil.rmtree(repo)
    make_run(home, repo, "orphaned", status="done", worktree=wt, ended=days_ago(clock, 8))
    assert not items_of(plan(home, cfg, now=clock.now()), "archive"), "8 days is not past keep_failed_days (14)"

    make_run(home, repo, "orphaned-old", status="done", worktree=wt, ended=days_ago(clock, 15))
    p = plan(home, cfg, now=clock.now())
    assert any(i.run_id == "orphaned-old" for i in items_of(p, "archive"))


def test_a_run_whose_repo_is_gone_keeps_its_worktree_on_disk(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "keepwt")
    shutil.rmtree(repo)
    make_run(home, repo, "keepwt", status="done", worktree=wt, ended=days_ago(clock, 15))

    report = apply(plan(home, cfg, now=clock.now()))

    assert "keepwt" in report.archived
    assert wt.exists(), "git cannot remove the worktree without its repo, so it stays and is reported"
    assert str(wt) in skipped_paths(report)


# --- retention and worker logs ---

def test_a_failed_run_archives_after_archive_days_but_keeps_its_worktree_for_keep_failed_days(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "failed-run")
    run_dir = make_run(home, repo, "failed-run", status="failed", worktree=wt, ended=days_ago(clock, 8))

    apply(plan(home, cfg, now=clock.now()))

    assert not run_dir.exists(), "the run folder is archived after archive_after_days (7)"
    assert wt.exists(), "the failed run's worktree waits keep_failed_days (14)"
    # Ended 8 days ago: due at 14 days after the end, which is 6 days from now. Seven days from now it is due.
    later = plan(home, cfg, now=clock.now() + timedelta(days=7))
    assert any(i.kind == "worktree" and i.path == wt for i in later.items)


def test_a_worker_log_over_the_cap_is_trimmed_only_for_a_run_that_is_kept(home, repo, cfg, clock):
    write_repo_config(repo, "retention:\n  worker_log_max_mb: 1\n")
    wt = worktree_for(cfg, repo, "log")
    run_dir = make_run(home, repo, "log", status="done", worktree=wt, tasks=[("backend", "done", None)],
                       ended=days_ago(clock, 2))
    log = run_dir / "tasks" / "backend" / "worker.log"
    log.write_bytes(b"a" * (1024 * 1024) + b"b" * (1024 * 1024) + b"NEWEST")

    report = apply(plan(home, cfg, now=clock.now()))

    data = log.read_bytes()
    assert data.endswith(b"NEWEST")
    assert len(data) == 1024 * 1024
    assert str(log) in report.trimmed


def test_an_active_run_is_never_removed(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "active-run")
    run_dir = make_run(home, repo, "active-run", status="awaiting_approval", worktree=wt,
                       ended=days_ago(clock, 90))
    apply(plan(home, cfg, now=clock.now()))
    assert run_dir.is_dir()
    assert wt.exists()


def test_a_pending_run_is_left_alone(home, repo, cfg, clock):
    make_run(home, repo, "pending", status="pending", worktree=repo, ended=days_ago(clock, 90))
    p = plan(home, cfg, now=clock.now())
    assert not any(i.run_id == "pending" for i in p.items)
