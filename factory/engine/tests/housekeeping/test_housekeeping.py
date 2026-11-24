"""Module 17 acceptance criteria. Git runs for real on temp repos; the clock is a FakeClock."""

import json
import shutil
import sys
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest

from factory_engine import gitops, housekeeping, state
from factory_engine.types import TaskBranch
from factory_engine.housekeeping import apply, cleanup_after_join, cleanup_after_merge, plan

sys.path.insert(0, str(Path(__file__).resolve().parent))
from housekeeping_helpers import KEY, branch_exists, dirty, days_ago, git_run, make_run, set_event_times, write_repo_config  # noqa: E402


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


# --- FIX 1: a run branch with commits no remote has is kept (task branches follow the join rule) ---

def commit_in(worktree, name="work.txt"):
    (worktree / name).write_text("work\n")
    git_run(worktree, "add", name)
    git_run(worktree, "commit", "-q", "-m", f"add {name}")


def add_origin(repo, tmp_path):
    bare = tmp_path / "origin.git"
    git_run(tmp_path, "init", "-q", "--bare", str(bare))
    git_run(repo, "remote", "add", "origin", str(bare))
    return bare


def test_a_run_branch_with_unpushed_commits_is_kept_and_reported(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "ahead")
    commit_in(wt, "one.txt")
    commit_in(wt, "two.txt")
    make_run(home, repo, "ahead", status="done", worktree=wt, ended=days_ago(clock, 8))

    report = apply(plan(home, cfg, now=clock.now()))

    assert wt.exists() and branch_exists(repo, "ahead"), "2 unpushed commits: the worktree and its branch stay"
    [kept] = [s for s in report.skipped if s.run_id == "ahead"]
    assert "ahead" in kept.reason and "2 unpushed commits" in kept.reason
    assert str(wt) not in report.removed


def test_gc_keeps_an_unjoined_task_branch_with_commits_and_deletes_a_joined_one(home, repo, cfg, clock):
    run_wt = worktree_for(cfg, repo, "mixed")
    joined_wt = task_worktree(cfg, repo, "mixed", "a")
    open_wt = task_worktree(cfg, repo, "mixed", "b")
    commit_in(joined_wt, "a.txt")
    commit_in(open_wt, "b.txt")
    gitops.join(run_wt, [TaskBranch("a", "mixed--a", "mixed")],
                regenerate=[], join_cmd=None)
    make_run(home, repo, "mixed", status="failed", worktree=run_wt, ended=days_ago(clock, 15),
             tasks=[("a", "done", joined_wt), ("b", "failed", open_wt)])

    report = apply(plan(home, cfg, now=clock.now()))

    assert not branch_exists(repo, "mixed--a"), "its join commit is on the run branch, so the join rule removes it"
    assert branch_exists(repo, "mixed--b"), "the task was never joined, and its commit is on no remote"
    assert any(s.run_id == "mixed" and "mixed--b" in s.reason for s in report.skipped)


def test_a_run_branch_whose_commits_are_on_a_remote_ref_is_deleted(home, repo, cfg, clock, tmp_path):
    wt = worktree_for(cfg, repo, "pushed")
    commit_in(wt)
    add_origin(repo, tmp_path)
    git_run(repo, "push", "-q", "origin", "pushed")
    make_run(home, repo, "pushed", status="done", worktree=wt, ended=days_ago(clock, 8))

    report = apply(plan(home, cfg, now=clock.now()))

    assert str(wt) in report.removed
    assert not branch_exists(repo, "pushed")


def test_cleanup_after_merge_deletes_a_run_branch_whose_commits_a_squash_merge_delivered(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "squashed")
    commit_in(wt)
    run_dir = make_run(home, repo, "squashed", status="done", worktree=wt)

    cleanup_after_merge(repo, cfg, state.read_run(run_dir))

    assert not wt.exists()
    assert not branch_exists(repo, "squashed"), "the pull request merged, so the merge is the evidence"


def test_a_joined_task_branch_with_commits_is_deleted_after_the_join(home, repo, cfg, clock):
    run_wt = worktree_for(cfg, repo, "joined3")
    task_wt = task_worktree(cfg, repo, "joined3", "backend")
    commit_in(task_wt)
    join = gitops.join(run_wt, [TaskBranch("backend", "joined3--backend", "joined3")], regenerate=[], join_cmd=None)
    assert join.ok and join.commits, "the join applied the task's diff and made its join commit"
    run_dir = make_run(home, repo, "joined3", status="running", worktree=run_wt,
                       tasks=[("backend", "done", task_wt)])

    cleanup_after_join(repo, cfg, state.read_run(run_dir), ["backend"])

    assert not task_wt.exists()
    assert not branch_exists(repo, "joined3--backend"), "task branches are never pushed; the join delivered them"


# --- FIX 2: a crash during the deletion never overwrites the complete zip ---

def test_a_second_gc_after_a_crash_in_the_deletion_keeps_the_complete_zip(home, repo, cfg, clock, monkeypatch):
    wt = worktree_for(cfg, repo, "crashy")
    run_dir = make_run(home, repo, "crashy", status="done", worktree=wt, tasks=[("backend", "done", None)],
                       ended=days_ago(clock, 8))
    (run_dir / "tasks" / "backend" / "worker.log").write_text("worker output\n")

    real_unlink = Path.unlink

    def crash_at_run_json(self, *a, **k):
        if self.name == "run.json":
            raise OSError("crash during the deletion")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", crash_at_run_json)
    first = apply(plan(home, cfg, now=clock.now()))
    monkeypatch.undo()

    assert first.failed and (run_dir / "run.json").is_file(), "a partial folder is left, as after a real crash"
    [zip_path] = (home / "archive").rglob("*.zip")
    before = zip_path.read_bytes()
    with zipfile.ZipFile(zip_path) as z:
        assert "tasks/backend/worker.log" in z.namelist()

    second = apply(plan(home, cfg, now=clock.now()))

    with zipfile.ZipFile(zip_path) as z:
        assert "tasks/backend/worker.log" in z.namelist(), "the zip still holds the whole log"
    assert zip_path.read_bytes() == before, "the complete zip is never overwritten"
    assert not run_dir.exists(), "the leftover folder is removed"
    assert str(run_dir) in second.deleted, "and the report says so"
    assert not second.failed
    assert [json.loads(l)["run_id"] for l in (home / "history.jsonl").read_text().splitlines()] == ["crashy"]


def test_a_leftover_folder_the_zip_does_not_match_is_kept_and_reported(home, repo, cfg, clock, monkeypatch):
    wt = worktree_for(cfg, repo, "mismatch")
    run_dir = make_run(home, repo, "mismatch", status="done", worktree=wt, ended=days_ago(clock, 8))
    real_unlink = Path.unlink

    def crash_at_run_json(self, *a, **k):
        if self.name == "run.json":
            raise OSError("crash during the deletion")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", crash_at_run_json)
    apply(plan(home, cfg, now=clock.now()))
    monkeypatch.undo()
    [zip_path] = (home / "archive").rglob("*.zip")
    before = zip_path.read_bytes()
    (run_dir / "stray.txt").write_text("written after the archive\n")

    report = apply(plan(home, cfg, now=clock.now()))

    assert zip_path.read_bytes() == before, "the zip is not touched"
    assert run_dir.is_dir(), "the folder is kept, because the zip does not hold all of it"
    assert any("stray.txt" in f.message for f in report.failed), "the report names the file"
    assert not report.deleted


def test_an_archive_zip_that_does_not_verify_is_written_again_from_the_folder(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "stale")
    run_dir = make_run(home, repo, "stale", status="done", worktree=wt, ended=days_ago(clock, 8))
    p = plan(home, cfg, now=clock.now())
    [item] = items_of(p, "archive")
    item.zip_path.parent.mkdir(parents=True, exist_ok=True)
    item.zip_path.write_bytes(b"not a zip")

    report = apply(p)

    assert not run_dir.exists()
    with zipfile.ZipFile(item.zip_path) as z:
        assert "run.json" in z.namelist()
    assert "stale" in report.archived


# --- FIX 3: a done run's worktree waits for its open pull request ---

def open_pr_for(run_dir, wt, prs, tmp_path, ended):
    body = tmp_path / "body.md"
    body.write_text("body\n")
    pr = prs.create(wt, base="main", head=wt.name, title="T", body_file=body, labels=[])
    run = state.read_run(run_dir)
    run.pr = pr
    lock = state.acquire_lock(run_dir, "test")
    state.write_run(run_dir, run, lock=lock)
    state.release(lock)
    set_event_times(run_dir, ended)  # writing the run added events; the run ended `ended`
    return pr


def test_an_open_pull_request_keeps_the_worktree_until_it_is_merged(home, repo, cfg, clock, tmp_path):
    from factory_engine.fake_prs import FakePullRequests
    prs = FakePullRequests()
    wt = worktree_for(cfg, repo, "waiting")
    commit_in(wt)
    add_origin(repo, tmp_path)
    git_run(repo, "push", "-q", "origin", "waiting")
    run_dir = make_run(home, repo, "waiting", status="done", worktree=wt, ended=days_ago(clock, 8))
    pr = open_pr_for(run_dir, wt, prs, tmp_path, days_ago(clock, 8))

    first = apply(plan(home, cfg, now=clock.now(), prs=prs))
    assert not run_dir.exists(), "the run is still archived"
    assert wt.exists() and branch_exists(repo, "waiting")
    assert any(s.run_id == "waiting" and s.reason == "pull request open" for s in first.skipped)

    again = apply(plan(home, cfg, now=clock.now(), prs=prs))
    assert wt.exists() and any(s.reason == "pull request open" for s in again.skipped), "a later gc reports it again"

    prs.human_merge(pr)
    last = apply(plan(home, cfg, now=clock.now(), prs=prs))
    assert str(wt) in last.removed and not wt.exists()
    assert not branch_exists(repo, "waiting")


def test_a_closed_pull_request_lets_the_worktree_go(home, repo, cfg, clock, tmp_path):
    from factory_engine.fake_prs import FakePullRequests
    prs = FakePullRequests()
    wt = worktree_for(cfg, repo, "closed")
    run_dir = make_run(home, repo, "closed", status="aborted", worktree=wt, ended=days_ago(clock, 15))
    pr = open_pr_for(run_dir, wt, prs, tmp_path, days_ago(clock, 15))
    prs.close(pr)

    report = apply(plan(home, cfg, now=clock.now(), prs=prs))

    assert str(wt) in report.removed
    assert not branch_exists(repo, "closed")


def test_a_pull_request_that_cannot_be_read_keeps_the_worktree_and_says_why(home, repo, cfg, clock, tmp_path):
    from factory_engine.fake_prs import FakePullRequests
    prs = FakePullRequests()
    wt = worktree_for(cfg, repo, "unreadable")
    run_dir = make_run(home, repo, "unreadable", status="done", worktree=wt, ended=days_ago(clock, 8))
    open_pr_for(run_dir, wt, prs, tmp_path, days_ago(clock, 8))
    prs.fail_next = RuntimeError("gh is down")

    report = apply(plan(home, cfg, now=clock.now(), prs=prs))

    assert wt.exists() and branch_exists(repo, "unreadable")
    [s] = [s for s in report.skipped if s.run_id == "unreadable"]
    assert "cannot be read" in s.reason and "gh is down" in s.detail


def test_a_run_with_a_pull_request_and_no_service_to_read_it_keeps_the_worktree(home, repo, cfg, clock, tmp_path):
    from factory_engine.fake_prs import FakePullRequests
    wt = worktree_for(cfg, repo, "noservice")
    run_dir = make_run(home, repo, "noservice", status="done", worktree=wt, ended=days_ago(clock, 8))
    open_pr_for(run_dir, wt, FakePullRequests(), tmp_path, days_ago(clock, 8))

    report = apply(plan(home, cfg, now=clock.now()))

    assert wt.exists() and branch_exists(repo, "noservice")
    assert any(s.run_id == "noservice" and "cannot be read" in s.reason for s in report.skipped)


def test_a_run_without_a_pull_request_is_not_held_by_gc(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "nopr")
    make_run(home, repo, "nopr", status="done", worktree=wt, ended=days_ago(clock, 8))

    report = apply(plan(home, cfg, now=clock.now()))

    assert str(wt) in report.removed and not wt.exists()


def test_api_gc_asks_the_pull_request_client_so_a_merged_pr_frees_the_worktree(home, repo, cfg, clock, tmp_path, monkeypatch):
    from factory_engine import api
    from factory_engine.fake_prs import FakePullRequests
    prs = FakePullRequests()
    monkeypatch.setattr(api, "load_config", lambda repo: cfg)
    monkeypatch.setattr(api, "default_prs", lambda repo, cfg: prs)
    monkeypatch.setenv("FACTORY_HOME", str(home))
    wt = worktree_for(cfg, repo, "viaapi")
    run_dir = make_run(home, repo, "viaapi", status="done", worktree=wt, ended=days_ago(clock, 8))
    pr = open_pr_for(run_dir, wt, prs, tmp_path, days_ago(clock, 8))

    api.gc(repo, apply=True)
    assert wt.exists(), "an open pull request keeps the worktree"

    prs.human_merge(pr)
    api.gc(repo, apply=True)
    assert not wt.exists(), "a merged pull request frees it"


# --- issue 86: gc reads the real GitHub client, one `gh pr view` per due run, and keeps what it cannot check ---

def _gh_stub(states, calls, *, fail=None):
    """A `gh` runner: replies to `pr view <n>` with states[n]; a number not in `states` is a deleted pull request."""
    import subprocess

    def run(args):
        calls.append(list(args))
        if fail:
            return subprocess.CompletedProcess(args, 1, "", fail)
        number = int(args[2])
        if number not in states:
            return subprocess.CompletedProcess(args, 1, "", "GraphQL: Could not resolve to a PullRequest with the number "
                                                            f"of {number}. (repository.pullRequest)")
        return subprocess.CompletedProcess(args, 0, json.dumps({"state": states[number], "statusCheckRollup": []}), "")
    return run


def _three_runs(home, repo, cfg, clock, tmp_path, names=("open", "merged", "closed")):
    """One ended run past retention per name, each with its own fake-created pull request (numbers 1, 2, 3)."""
    from factory_engine.fake_prs import FakePullRequests
    maker = FakePullRequests()
    wts = {}
    for name in names:
        wts[name] = worktree_for(cfg, repo, name)
        run_dir = make_run(home, repo, name, status="done", worktree=wts[name], ended=days_ago(clock, 8))
        open_pr_for(run_dir, wts[name], maker, tmp_path, days_ago(clock, 8))
    return wts


def test_gc_asks_github_once_per_due_run_and_frees_only_the_merged_and_closed(home, repo, cfg, clock, tmp_path):
    from factory_engine.gh import GitHubPullRequests
    wts = _three_runs(home, repo, cfg, clock, tmp_path)
    calls = []
    prs = GitHubPullRequests(runner=_gh_stub({1: "OPEN", 2: "MERGED", 3: "CLOSED"}, calls))

    p = plan(home, cfg, now=clock.now(), prs=prs)
    report = apply(p)

    assert sorted(i.run_id for i in items_of(p, "worktree")) == ["closed", "merged"]
    assert wts["open"].exists() and not wts["merged"].exists() and not wts["closed"].exists()
    assert [c[:2] for c in calls] == [["pr", "view"]] * 3 and sorted(c[2] for c in calls) == ["1", "2", "3"]
    assert [s.reason for s in report.skipped if s.run_id == "open"] == ["pull request open"]


def test_gc_does_not_ask_github_about_a_run_that_is_not_due(home, repo, cfg, clock, tmp_path):
    from factory_engine.fake_prs import FakePullRequests
    from factory_engine.gh import GitHubPullRequests
    wt = worktree_for(cfg, repo, "young")
    run_dir = make_run(home, repo, "young", status="done", worktree=wt, ended=days_ago(clock, 1))
    open_pr_for(run_dir, wt, FakePullRequests(), tmp_path, days_ago(clock, 1))
    calls = []

    apply(plan(home, cfg, now=clock.now(), prs=GitHubPullRequests(runner=_gh_stub({1: "MERGED"}, calls))))

    assert calls == [] and wt.exists()


def test_gc_removes_nothing_and_says_why_when_gh_cannot_reach_github(home, repo, cfg, clock, tmp_path):
    from factory_engine.gh import GitHubPullRequests
    wts = _three_runs(home, repo, cfg, clock, tmp_path)
    prs = GitHubPullRequests(runner=_gh_stub({}, [], fail="To get started with GitHub CLI, please run:  gh auth login"))

    report = apply(plan(home, cfg, now=clock.now(), prs=prs))

    assert all(w.exists() for w in wts.values()) and report.removed == []
    held = {s.run_id: s for s in report.skipped if s.run_id in wts}
    assert set(held) == set(wts)
    assert all(s.reason == "pull request cannot be read" and "gh auth login" in s.detail for s in held.values())


def test_a_deleted_pull_request_keeps_its_worktree_and_is_reported_not_treated_as_closed(home, repo, cfg, clock, tmp_path):
    from factory_engine.gh import GitHubPullRequests
    wts = _three_runs(home, repo, cfg, clock, tmp_path, names=("gone",))
    prs = GitHubPullRequests(runner=_gh_stub({}, []))

    report = apply(plan(home, cfg, now=clock.now(), prs=prs))

    assert wts["gone"].exists() and branch_exists(repo, "gone") and report.removed == []
    [s] = [s for s in report.skipped if s.run_id == "gone"]
    assert s.reason == "pull request cannot be read" and "Could not resolve to a PullRequest" in s.detail


def test_a_deleted_pull_request_in_the_fake_is_kept_the_same_way(home, repo, cfg, clock, tmp_path):
    from factory_engine.fake_prs import FakePullRequests
    prs = FakePullRequests()
    wt = worktree_for(cfg, repo, "gone")
    run_dir = make_run(home, repo, "gone", status="done", worktree=wt, ended=days_ago(clock, 8))
    open_pr_for(run_dir, wt, prs, tmp_path, days_ago(clock, 8))
    del prs.prs[1]

    report = apply(plan(home, cfg, now=clock.now(), prs=prs))

    assert wt.exists() and any(s.run_id == "gone" and s.reason == "pull request cannot be read" for s in report.skipped)


# --- issue #89: the seven unticked criteria (lines 127 and 129 to 134 of module 17) ---

def test_a_running_runs_worker_log_is_not_cut_and_an_ended_kept_one_is_cut_to_its_newest_bytes(home, repo, cfg, clock):
    """Line 127: a running run's log over the cap is left whole; an ended run that is kept is cut to its newest bytes."""
    write_repo_config(repo, "retention:\n  worker_log_max_mb: 1\n")
    wt_run = worktree_for(cfg, repo, "live")
    running = make_run(home, repo, "live", status="running", worktree=wt_run, tasks=[("backend", "running", None)],
                       ended=None)
    big = b"a" * (1024 * 1024) + b"b" * (1024 * 1024) + b"NEWEST"
    (running / "tasks" / "backend" / "worker.log").write_bytes(big)
    wt_done = worktree_for(cfg, repo, "kept")
    ended = make_run(home, repo, "kept", status="done", worktree=wt_done, tasks=[("backend", "done", None)],
                     ended=days_ago(clock, 2))
    (ended / "tasks" / "backend" / "worker.log").write_bytes(big)

    report = apply(plan(home, cfg, now=clock.now()))

    assert (running / "tasks" / "backend" / "worker.log").read_bytes() == big
    kept = (ended / "tasks" / "backend" / "worker.log").read_bytes()
    assert kept.endswith(b"NEWEST") and len(kept) == 1024 * 1024
    assert str(running / "tasks" / "backend" / "worker.log") not in report.trimmed


def _archived_run(home, repo, cfg, clock, run_id, written_days_ago):
    """An archived run: its zip written `written_days_ago` before now, with no folder left."""
    wt = worktree_for(cfg, repo, run_id)
    run_dir = make_run(home, repo, run_id, status="done", worktree=wt, ended=days_ago(clock, 30))
    apply(plan(home, cfg, now=clock.now()))  # archives it: the run ended 30 days ago, past archive_after_days
    zips = sorted((home / "archive").rglob(f"*{run_id}*.zip"))
    assert zips, "the run should have been archived"
    written = (clock.now() - timedelta(days=written_days_ago)).timestamp()
    import os
    for z in zips:
        os.utime(z, (written, written))
    return zips[0]


def test_an_archive_zip_is_deleted_once_delete_archive_after_days_have_passed_and_not_one_day_before(home, repo, cfg, clock):
    """Line 129: gc --apply deletes an archive zip when delete_archive_after_days (90) have passed since it was written."""
    zp = _archived_run(home, repo, cfg, clock, "old-zip", written_days_ago=0)
    assert zp.exists()
    import os
    written = clock.now() - timedelta(days=89)
    os.utime(zp, (written.timestamp(), written.timestamp()))
    apply(plan(home, cfg, now=clock.now()))
    assert zp.exists(), "89 days is not past delete_archive_after_days (90)"

    written = clock.now() - timedelta(days=90)
    os.utime(zp, (written.timestamp(), written.timestamp()))
    report = apply(plan(home, cfg, now=clock.now()))
    assert not zp.exists() and str(zp) in report.deleted


def test_git_worktree_prune_runs_in_each_repo_with_a_worktree_item_after_apply_and_clears_gone_records(home, repo, cfg, clock):
    """Line 130: after apply, `git worktree prune` runs in each repo that had a worktree or archive item, so a record
    whose folder is gone is cleared."""
    wt = worktree_for(cfg, repo, "pruned")
    make_run(home, repo, "pruned", status="done", worktree=wt, ended=days_ago(clock, 8))
    p = plan(home, cfg, now=clock.now())
    assert any(i.kind == "archive" and i.repo == repo for i in p.items)
    shutil.rmtree(wt)  # the worktree folder goes, so git still has a record of it
    assert "pruned" in git_run(repo, "worktree", "list", "--porcelain")
    apply(p)
    assert "pruned" not in git_run(repo, "worktree", "list", "--porcelain")


def test_a_failed_runs_worktree_is_due_at_exactly_keep_failed_days_and_not_one_day_before(home, repo, cfg, clock):
    """Line 131: a failed run's worktrees are due at exactly keep_failed_days (14) after its end."""
    wt = worktree_for(cfg, repo, "due-failed")
    make_run(home, repo, "due-failed", status="failed", worktree=wt, ended=days_ago(clock, 0))
    assert not any(i.kind == "worktree" and i.path == wt
                   for i in plan(home, cfg, now=clock.now() + timedelta(days=13, hours=23)).items)
    assert any(i.kind == "worktree" and i.path == wt
               for i in plan(home, cfg, now=clock.now() + timedelta(days=14)).items)


def test_a_run_is_archived_at_exactly_archive_after_days_and_not_one_day_before(home, repo, cfg, clock):
    """Line 132: a done run is archived at exactly archive_after_days (7) after its end."""
    wt = worktree_for(cfg, repo, "due-done")
    make_run(home, repo, "due-done", status="done", worktree=wt, ended=days_ago(clock, 0))
    assert not items_of(plan(home, cfg, now=clock.now() + timedelta(days=6, hours=23)), "archive")
    assert [i for i in items_of(plan(home, cfg, now=clock.now() + timedelta(days=7)), "archive")
            if i.run_id == "due-done"]


def test_a_failed_removal_is_reported_and_the_other_items_still_run(home, repo, cfg, clock, monkeypatch):
    """Line 133: a failed worktree, branch, kit or archive-delete removal appears in GcReport.failed, and the rest run."""
    zp = _archived_run(home, repo, cfg, clock, "old-zip", written_days_ago=200)  # a real archive, past its 90 days
    wt_bad = worktree_for(cfg, repo, "bad-wt")
    wt_good = worktree_for(cfg, repo, "good-wt")
    make_run(home, repo, "bad-wt", status="done", worktree=wt_bad, ended=days_ago(clock, 30))
    make_run(home, repo, "good-wt", status="done", worktree=wt_good, ended=days_ago(clock, 30))
    kit = home / "kits" / "orphan-kit"
    kit.mkdir(parents=True)
    (kit / "x").write_text("x")
    import os

    real_rmtree = shutil.rmtree

    def rmtree(path, *a, **k):
        if Path(path) == kit:
            raise OSError("disk says no")
        return real_rmtree(path, *a, **k)

    monkeypatch.setattr(housekeeping.shutil, "rmtree", rmtree)
    real_unlink = Path.unlink

    def unlink(self, *a, **k):
        if self == zp:
            raise OSError("zip is locked")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)

    report = apply(plan(home, cfg, now=clock.now()))

    failed = {str(f.path) for f in report.failed}
    assert str(kit) in failed and str(zp) in failed
    assert "could not delete the kit" in " ".join(f.message for f in report.failed)
    assert not wt_good.exists() and str(wt_good) in report.removed, "the other worktree still went"


def test_an_archive_that_fails_testzip_is_not_moved_into_place_and_the_run_folder_is_kept(home, repo, cfg, clock, monkeypatch):
    """Line 134: an archive that fails testzip(), or whose members differ from the folder, is not moved into place and
    the run folder is kept."""
    wt = worktree_for(cfg, repo, "bad-zip")
    run_dir = make_run(home, repo, "bad-zip", status="done", worktree=wt, ended=days_ago(clock, 30))

    real_testzip = zipfile.ZipFile.testzip
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda self: "member.json")  # every archive is corrupt
    report = apply(plan(home, cfg, now=clock.now()))
    monkeypatch.setattr(zipfile.ZipFile, "testzip", real_testzip)

    assert run_dir.exists(), "the folder is kept when the archive does not verify"
    assert "bad-zip" not in report.archived
    assert not list((home / "archive").rglob("*bad-zip*.zip")), "a zip that fails testzip is not moved into place"


def test_an_archive_whose_members_differ_from_the_folder_is_not_moved_into_place_and_the_run_folder_is_kept(
        home, repo, cfg, clock, monkeypatch):
    """Line 134, second half: a zip that passes testzip() but lists a different set of files than the run folder is
    not moved into place, and the run folder is kept."""
    wt = worktree_for(cfg, repo, "short-zip")
    run_dir = make_run(home, repo, "short-zip", status="done", worktree=wt, ended=days_ago(clock, 30))

    real_write = zipfile.ZipFile.write

    def write_with_an_extra_member(self, filename, arcname=None, *a, **k):
        real_write(self, filename, arcname, *a, **k)
        if arcname == "run.json":
            self.writestr("stray.txt", "a member the run folder does not have")  # byte-compare never reads it

    monkeypatch.setattr(zipfile.ZipFile, "write", write_with_an_extra_member)
    report = apply(plan(home, cfg, now=clock.now()))
    monkeypatch.setattr(zipfile.ZipFile, "write", real_write)

    assert run_dir.exists(), "the folder is kept when the archive lists different files"
    assert "short-zip" not in report.archived
    assert any("not archived" in f.message for f in report.failed)
    assert not list((home / "archive").rglob("*short-zip*.zip"))


def test_a_failed_worktree_removal_and_a_failed_branch_delete_are_reported_and_the_other_items_still_run(
        home, repo, cfg, clock, monkeypatch):
    """Line 133, the worktree and branch halves: each failure lands in GcReport.failed and the next worktree still goes."""
    from factory_engine.errors import FactoryError
    wt_a = worktree_for(cfg, repo, "stuck-wt")
    wt_b = worktree_for(cfg, repo, "stuck-branch")
    wt_c = worktree_for(cfg, repo, "fine")
    for rid, wt in (("stuck-wt", wt_a), ("stuck-branch", wt_b), ("fine", wt_c)):
        make_run(home, repo, rid, status="done", worktree=wt, ended=days_ago(clock, 30))

    real_remove, real_delete = housekeeping.remove_worktree, housekeeping.delete_branch

    def remove(path, **k):
        if Path(path) == wt_a:
            raise FactoryError("git.command_failed", "worktree is locked")
        return real_remove(path, **k)

    def delete(repo_, branch, **k):
        if branch == "stuck-branch":
            raise FactoryError("git.command_failed", "branch is checked out elsewhere")
        return real_delete(repo_, branch, **k)

    monkeypatch.setattr(housekeeping, "remove_worktree", remove)
    monkeypatch.setattr(housekeeping, "delete_branch", delete)

    report = apply(plan(home, cfg, now=clock.now()))

    messages = {Path(f.path): f.message for f in report.failed}
    assert "worktree is locked" in messages[wt_a]
    assert "branch stuck-branch kept" in messages[wt_b]
    assert str(wt_c) in report.removed and not wt_c.exists(), "the third worktree still went"


def test_an_archive_with_a_member_that_differs_from_its_file_is_not_moved_into_place_and_the_run_folder_is_kept(
        home, repo, cfg, clock, monkeypatch):
    """Line 134, third part: a zip whose member has different bytes than the file in the run folder is not moved into
    place, and the run folder is kept."""
    wt = worktree_for(cfg, repo, "wrong-bytes")
    run_dir = make_run(home, repo, "wrong-bytes", status="done", worktree=wt, ended=days_ago(clock, 30))

    real_write = zipfile.ZipFile.write

    def write_wrong_bytes(self, filename, arcname=None, *a, **k):
        if arcname == "events.jsonl":
            return self.writestr(arcname, "not the folder's events\n")  # a member that is present but has other bytes
        return real_write(self, filename, arcname, *a, **k)

    monkeypatch.setattr(zipfile.ZipFile, "write", write_wrong_bytes)
    report = apply(plan(home, cfg, now=clock.now()))
    monkeypatch.setattr(zipfile.ZipFile, "write", real_write)

    assert run_dir.exists(), "the folder is kept when a member differs"
    assert "wrong-bytes" not in report.archived
    assert any("archive differs from events.jsonl" in f.message for f in report.failed)
    assert not list((home / "archive").rglob("*wrong-bytes*.zip"))


def test_an_archived_worker_log_is_whole_when_no_earlier_gc_cut_it_and_cut_when_one_did(home, repo, cfg, clock):
    """Module 17, the archived worker.log: it is the copy as it was at archive time. A run archived at once keeps the
    whole log; a run an earlier gc cut keeps the cut copy, because an archive is made as the run is, without a cut."""
    write_repo_config(repo, "retention:\n  worker_log_max_mb: 1\n")
    mb = 1024 * 1024
    big = b"a" * mb + b"b" * mb + b"NEWEST"

    def archived_log(run_id, ended_days, *, cut_first):
        wt = worktree_for(cfg, repo, run_id)
        run_dir = make_run(home, repo, run_id, status="done", worktree=wt, tasks=[("backend", "done", None)],
                           ended=days_ago(clock, ended_days))
        log = run_dir / "tasks" / "backend" / "worker.log"
        log.write_bytes(big)
        if cut_first:
            apply(plan(home, cfg, now=clock.now()))                      # ended 2 days ago, not yet due: its log is cut
            assert len(log.read_bytes()) == mb
            apply(plan(home, cfg, now=clock.now() + timedelta(days=6)))  # a later gc archives it, now due
        else:
            apply(plan(home, cfg, now=clock.now()))                      # ended 8 days ago, due at once: archived as it is
        [zp] = [z for z in (home / "archive").rglob("*.zip") if run_id in z.name]
        with zipfile.ZipFile(zp) as z:
            return z.read("tasks/backend/worker.log")

    assert archived_log("never-cut", 8, cut_first=False) == big, "no earlier gc cut it: the archive keeps it whole"
    cut = archived_log("cut-first", 2, cut_first=True)
    assert cut == big[-mb:] and cut.endswith(b"NEWEST"), "an earlier gc cut it: the archive keeps the cut copy"


def test_a_run_that_resumes_between_plan_and_apply_keeps_its_worktree(home, repo, cfg, clock):
    """Module 17: an active run is never touched. The plan sees a failed run and lists its worktree; a run that is
    resumed before apply is running again, with a live engine, and its worktree must stay."""
    wt = worktree_for(cfg, repo, "resumed")
    run_dir = make_run(home, repo, "resumed", status="failed", worktree=wt, ended=days_ago(clock, 20))
    planned = plan(home, cfg, now=clock.now())
    assert any(i.kind == "worktree" and i.path == wt for i in planned.items), "the plan lists the worktree"

    # the run is resumed: its status goes back to running and an engine takes the lock
    lock = state.acquire_lock(run_dir, "engine")
    run = state.read_run(run_dir)
    run.status = "running"
    state.write_run(run_dir, run, lock=lock)

    report = apply(planned)

    assert wt.exists(), "apply re-reads the run before it removes a worktree"
    assert [s.reason for s in report.skipped if s.path == wt] == ["an engine holds the run lock; the worktree is kept"]
    state.release(lock)


def test_a_run_that_resumes_between_plan_and_apply_keeps_its_worker_log_whole(home, repo, cfg, clock):
    write_repo_config(repo, "retention:\n  worker_log_max_mb: 1\n")
    wt = worktree_for(cfg, repo, "resumed-log")
    run_dir = make_run(home, repo, "resumed-log", status="done", worktree=wt, tasks=[("backend", "done", None)],
                       ended=days_ago(clock, 2))
    log = run_dir / "tasks" / "backend" / "worker.log"
    log.write_bytes(b"a" * (1024 * 1024) + b"b" * (1024 * 1024) + b"NEWEST")
    planned = plan(home, cfg, now=clock.now())
    assert any(i.kind == "worker_log" for i in planned.items), "the plan lists the log"

    lock = state.acquire_lock(run_dir, "engine")
    run = state.read_run(run_dir)
    run.status = "running"
    state.write_run(run_dir, run, lock=lock)

    report = apply(planned)

    assert log.stat().st_size == 2 * 1024 * 1024 + len(b"NEWEST"), "a running task is still writing this log"
    assert str(log) not in report.trimmed
    assert [s.reason for s in report.skipped if s.path == log] == ["an engine holds the run lock; the log is not cut"]
    state.release(lock)


def test_a_run_that_ends_again_without_a_lock_is_still_not_removed_by_a_stale_plan(home, repo, cfg, clock):
    """The re-read also covers a run whose status changed without a lock held: here it is running and nobody holds the lock."""
    wt = worktree_for(cfg, repo, "reopened")
    run_dir = make_run(home, repo, "reopened", status="failed", worktree=wt, ended=days_ago(clock, 20))
    planned = plan(home, cfg, now=clock.now())
    run = state.read_run(run_dir)
    run.status = "running"
    lock = state.acquire_lock(run_dir, "test")
    state.write_run(run_dir, run, lock=lock)
    state.release(lock)

    report = apply(planned)

    assert wt.exists()
    assert [s.reason for s in report.skipped if s.path == wt] == ["the run is no longer ended; the worktree is kept"]


def test_an_unreadable_run_json_at_apply_is_reported_and_the_pass_goes_on(home, repo, cfg, clock):
    wt = worktree_for(cfg, repo, "corrupt")
    run_dir = make_run(home, repo, "corrupt", status="failed", worktree=wt, ended=days_ago(clock, 20))
    planned = plan(home, cfg, now=clock.now())
    (run_dir / "run.json").write_text("{not json")

    report = apply(planned)

    assert wt.exists()
    assert any(f.path == wt and "could not re-read" in f.message for f in report.failed)
