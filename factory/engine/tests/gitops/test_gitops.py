"""Module 7 acceptance criteria covered by the engine's git layer so far."""

from pathlib import Path

import pytest

from factory_engine import gitops
from factory_engine.errors import FactoryError

import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent))
from gitutil import ls_remote, run  # noqa: E402


def worktree_path(cfg, run_id):
    return Path(cfg.machine["worktree_root"]) / "repo" / run_id


def test_run_worktree_is_created_at_worktree_path_on_a_run_branch(repo, cfg):
    path = gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    assert path == worktree_path(cfg, "run-1")
    assert run(path, "rev-parse", "--abbrev-ref", "HEAD") == "run-1"


def test_read_only_run_is_detached_and_gets_a_branch_only_at_delivery(repo, cfg):
    path = gitops.create_run_worktree(repo, cfg, "ro-1", base="main", detached=True)
    assert run(path, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"  # detached
    assert "ro-1" not in run(repo, "branch", "--list", "ro-1")
    gitops.create_delivery_branch(path, "ro-1")
    assert run(path, "rev-parse", "--abbrev-ref", "HEAD") == "ro-1"


def test_worktree_outside_the_repo_or_already_present_is_refused(repo, cfg, tmp_path):
    gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    with pytest.raises(FactoryError, match="already exists"):
        gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)


def test_run_marker_is_written_and_excluded_from_git(repo, cfg, tmp_path):
    path = gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    gitops.mark_run(path, tmp_path / "runs" / "run-1", "run-1", "local/repo")
    assert (path / gitops.RUN_MARKER).is_file()
    assert run(path, "status", "--porcelain") == ""  # excluded: the marker is not an untracked change


def test_checkpoint_commits_product_files_and_never_the_marker(repo, cfg, tmp_path):
    path = gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    gitops.mark_run(path, tmp_path / "r", "run-1", "k")
    gitops.create_task_worktree(repo, cfg, "run-1", "backend", base_branches=["run-1"])
    tw = Path(cfg.machine["worktree_root"]) / "repo" / "run-1--backend"
    (tw / "services" / "api.py").write_text("x = 2\n")
    gitops.mark_run(tw, tmp_path / "r", "run-1", "k")
    sha = gitops.checkpoint(tw, "backend", 1)
    assert sha is not None
    files = run(tw, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert files == ["services/api.py"]  # the marker is excluded and never staged


def test_checkpoint_message_and_no_change_returns_none(repo, cfg):
    gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    gitops.create_task_worktree(repo, cfg, "run-1", "backend", base_branches=["run-1"])
    tw = Path(cfg.machine["worktree_root"]) / "repo" / "run-1--backend"
    assert gitops.checkpoint(tw, "backend", 1) is None  # nothing changed
    (tw / "web" / "app.js").write_text("y = 2\n")
    gitops.checkpoint(tw, "backend", 2)
    assert run(tw, "log", "-1", "--format=%s") == "wip(backend): checkpoint 2"


def test_checkpoint_skips_repo_hooks(repo, cfg):
    gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    gitops.create_task_worktree(repo, cfg, "run-1", "backend", base_branches=["run-1"])
    tw = Path(cfg.machine["worktree_root"]) / "repo" / "run-1--backend"
    hook = tw / ".git" if (tw / ".git").is_dir() else Path(run(tw, "rev-parse", "--git-path", "hooks"))
    hooks = Path(run(tw, "rev-parse", "--path-format=absolute", "--git-path", "hooks"))
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n")
    (hooks / "pre-commit").chmod(0o755)
    (tw / "web" / "app.js").write_text("y = 3\n")
    assert gitops.checkpoint(tw, "backend", 1) is not None  # a failing pre-commit hook does not stop a checkpoint


def test_checkpoints_stay_local_and_are_never_pushed(repo, cfg):
    gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    gitops.create_task_worktree(repo, cfg, "run-1", "backend", base_branches=["run-1"])
    tw = Path(cfg.machine["worktree_root"]) / "repo" / "run-1--backend"
    (tw / "web" / "app.js").write_text("y = 4\n")
    gitops.checkpoint(tw, "backend", 1)
    refs = ls_remote(repo)
    assert not any("run-1--backend" in r for r in refs)  # no task branch on the remote


def test_changed_files_and_the_scope_check(repo, cfg):
    gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    gitops.create_task_worktree(repo, cfg, "run-1", "backend", base_branches=["run-1"])
    tw = Path(cfg.machine["worktree_root"]) / "repo" / "run-1--backend"
    (tw / "services" / "api.py").write_text("x = 9\n")
    (tw / "web" / "app.js").write_text("y = 9\n")
    gitops.checkpoint(tw, "backend", 1)
    changed = gitops.changed_files(tw, "run-1")
    assert sorted(changed) == ["services/api.py", "web/app.js"]
    assert gitops.check_scope_diff_paths(changed, ["services/**"], []) == ["web/app.js"]


def test_deny_wins_over_scope_including_deny_added_later(repo):
    files = ["services/api.py", "services/auth/token.py"]
    assert gitops.check_scope_diff_paths(files, ["services/**"], []) == []
    assert gitops.check_scope_diff_paths(files, ["services/**"], ["services/auth/*"]) == ["services/auth/token.py"]


def test_remove_worktree_from_the_path_alone(repo, cfg):
    path = gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    gitops.remove_worktree(path)
    assert not path.exists()


def test_a_dirty_worktree_is_refused_unless_forced(repo, cfg):
    path = gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    (path / "services" / "api.py").write_text("dirty\n")
    with pytest.raises(FactoryError):
        gitops.remove_worktree(path)
    gitops.remove_worktree(path, force=True)
    assert not path.exists()


def test_the_engine_never_deletes_a_remote_task_branch(repo):
    with pytest.raises(FactoryError, match="does not delete remote task branches"):
        gitops.delete_branch(repo, "run-1--backend", remote=True)


# ---------------- join, sync and push ----------------

from factory_engine.types import TaskBranch  # noqa: E402


def make_task(repo, cfg, run_id, task_id, files, *, bases=None, msg="change"):
    """Create a task worktree, write files, checkpoint, and return its TaskBranch."""
    gitops.create_task_worktree(repo, cfg, run_id, task_id, base_branches=bases or [run_id])
    tw = Path(cfg.machine["worktree_root"]) / "repo" / f"{run_id}--{task_id}"
    base = run(tw, "rev-parse", "HEAD")
    for rel, text in files.items():
        (tw / rel).parent.mkdir(parents=True, exist_ok=True)
        (tw / rel).write_text(text)
    gitops.checkpoint(tw, task_id, 1)
    return TaskBranch(task_id=task_id, branch=f"{run_id}--{task_id}", task_base=base)


def start_run(repo, cfg, run_id="run-1"):
    return gitops.create_run_worktree(repo, cfg, run_id, base="main", detached=False)


def test_join_commits_each_task_once_in_order(repo, cfg):
    rw = start_run(repo, cfg)
    a = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    b = make_task(repo, cfg, "run-1", "b", {"web/app.js": "y = 'b'\n"})
    r = gitops.join(rw, [a, b], regenerate=[], join_cmd=None)
    assert r.ok and len(r.commits) == 2
    log = run(rw, "log", "--format=%s", "main..HEAD").splitlines()
    assert log == ["task(b): joined from run-1--b", "task(a): joined from run-1--a"]


def test_a_chained_task_never_reapplies_its_dependency_and_the_run_branch_holds_one_commit_per_task(repo, cfg):
    rw = start_run(repo, cfg)
    a = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    # b needs a: it starts from a's branch and sees a's change
    b = make_task(repo, cfg, "run-1", "b", {"web/app.js": "y = 'b'\n"}, bases=["run-1--a"])
    tw_b = Path(cfg.machine["worktree_root"]) / "repo" / "run-1--b"
    assert (tw_b / "services" / "api.py").read_text() == "x = 'a'\n"  # sees the dependency's change
    r = gitops.join(rw, [a, b], regenerate=[], join_cmd=None)
    assert r.ok and len(r.commits) == 2
    assert run(rw, "rev-list", "--count", "main..HEAD") == "2"  # one commit per task, no change twice
    assert (rw / "services" / "api.py").read_text() == "x = 'a'\n" and (rw / "web" / "app.js").read_text() == "y = 'b'\n"


def test_a_conflicting_join_leaves_the_run_branch_at_its_last_good_commit(repo, cfg):
    rw = start_run(repo, cfg)
    a = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    b = make_task(repo, cfg, "run-1", "b", {"services/api.py": "x = 'b'\n"})  # same file, same lines
    before = run(rw, "rev-parse", "HEAD")
    r = gitops.join(rw, [a, b], regenerate=[], join_cmd=None)
    assert not r.ok and r.conflict_files == ["services/api.py"] and not r.hook_failed
    assert run(rw, "rev-parse", "HEAD") == before          # reset to the commit before the join began
    assert run(rw, "status", "--porcelain") == ""          # no conflict markers left behind


def test_two_tasks_adding_dependencies_end_with_one_regenerated_lockfile(repo, cfg):
    run(repo, "checkout", "-q", "main")
    (repo / "package-lock.json").write_text('{"v": 0}\n')
    run(repo, "add", "-A"); run(repo, "commit", "-q", "-m", "lock"); run(repo, "push", "-q", "origin", "main")
    rw = start_run(repo, cfg)
    a = make_task(repo, cfg, "run-1", "a", {"package-lock.json": '{"v": "a"}\n', "services/api.py": "x = 'a'\n"})
    b = make_task(repo, cfg, "run-1", "b", {"package-lock.json": '{"v": "b"}\n', "web/app.js": "y = 'b'\n"})
    # join_cmd rebuilds the lockfile once, from the merged state
    cmd = ["python3", "-c", "open('package-lock.json','w').write('{\"v\": \"rebuilt\"}\\n')"]
    r = gitops.join(rw, [a, b], regenerate=["package-lock.json"], join_cmd=cmd)
    assert r.ok, r
    assert (rw / "package-lock.json").read_text() == '{"v": "rebuilt"}\n'
    assert run(rw, "log", "--format=%s", "-1") == "chore: regenerate lockfiles at join"
    # only the commits the join made on the run branch: the setup commit on main is not part of the run
    locks = run(rw, "log", "--format=%s", "main..HEAD", "--", "package-lock.json").splitlines()
    assert locks == ["chore: regenerate lockfiles at join"]  # the task commits never touched it


def test_a_failing_repo_hook_on_a_task_commit_is_returned_as_hook_failed(repo, cfg):
    rw = start_run(repo, cfg)
    a = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    hooks = Path(run(rw, "rev-parse", "--path-format=absolute", "--git-path", "hooks"))
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n")
    (hooks / "pre-commit").chmod(0o755)
    before = run(rw, "rev-parse", "HEAD")
    r = gitops.join(rw, [a], regenerate=[], join_cmd=None)
    assert not r.ok and r.hook_failed and r.conflict_files == []
    assert run(rw, "rev-parse", "HEAD") == before


def test_sync_base_returns_a_conflict_and_resets(repo, cfg):
    rw = start_run(repo, cfg)
    (rw / "services" / "api.py").write_text("x = 'run'\n")
    run(rw, "add", "-A"); run(rw, "commit", "-q", "-m", "run change")
    # the base moves on, touching the same line
    (repo / "services" / "api.py").write_text("x = 'base'\n")
    run(repo, "add", "-A"); run(repo, "commit", "-q", "-m", "base change"); run(repo, "push", "-q", "origin", "main")
    before = run(rw, "rev-parse", "HEAD")
    r = gitops.sync_base(rw, "main")
    assert not r.ok and r.conflict_files == ["services/api.py"]
    assert run(rw, "rev-parse", "HEAD") == before and run(rw, "status", "--porcelain") == ""


def test_sync_base_merges_a_clean_base_change(repo, cfg):
    rw = start_run(repo, cfg)
    (repo / "web" / "app.js").write_text("y = 'base'\n")
    run(repo, "add", "-A"); run(repo, "commit", "-q", "-m", "base change"); run(repo, "push", "-q", "origin", "main")
    assert gitops.sync_base(rw, "main").ok
    assert (rw / "web" / "app.js").read_text() == "y = 'base'\n"


def test_push_sends_only_the_run_branch_with_join_commits_and_no_wip(repo, cfg):
    rw = start_run(repo, cfg)
    a = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    tw = Path(cfg.machine["worktree_root"]) / "repo" / "run-1--a"
    (tw / "web" / "app.js").write_text("y = 'a2'\n")
    gitops.checkpoint(tw, "a", 2)  # several checkpoints per task
    a = TaskBranch("a", "run-1--a", a.task_base)
    assert gitops.join(rw, [a], regenerate=[], join_cmd=None).ok
    gitops.push(rw, "run-1")
    refs = ls_remote(repo)
    assert sorted(r for r in refs if r != "HEAD") == ["refs/heads/main", "refs/heads/run-1"]  # no task branch, nothing else
    pushed = run(repo, "log", "--format=%s", "origin/run-1").splitlines()
    assert not any(s.startswith("wip(") for s in pushed)  # no wip commit is reachable from the pushed branch
    assert any(s.startswith("task(a):") for s in pushed)


def test_the_engine_refuses_to_push_the_base_branch(repo, cfg):
    rw = start_run(repo, cfg)
    with pytest.raises(FactoryError, match="never pushes the base branch"):
        gitops.push(rw, "main")


def test_a_worker_that_commits_does_not_change_what_the_engine_counts(repo, cfg):
    """A worker that runs `git commit` adds a commit the engine did not make; the engine's own checkpoint
    still returns its own sha, and the join diff is the task's net change from its base, so nothing doubles."""
    rw = start_run(repo, cfg)
    t = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    tw = Path(cfg.machine["worktree_root"]) / "repo" / "run-1--a"
    (tw / "web" / "app.js").write_text("y = 'worker commit'\n")
    run(tw, "add", "-A"); run(tw, "commit", "-q", "-m", "worker made this commit")
    assert gitops.join(rw, [t], regenerate=[], join_cmd=None).ok
    assert run(rw, "rev-list", "--count", "main..HEAD") == "1"  # still one join commit for the task
    assert (rw / "web" / "app.js").read_text() == "y = 'worker commit'\n"


# ---------------- kit snapshot, conflict signals, scope gate ----------------

from factory_engine.types import GateContext, GateSpec  # noqa: E402


def commit_kit(repo, workflow_text="name: bug-fix\n", config_text="base_branch: main\n"):
    (repo / "factory" / "workflows").mkdir(parents=True, exist_ok=True)
    (repo / "factory" / "workflows" / "bug-fix.yaml").write_text(workflow_text)
    (repo / ".factory" / "config").mkdir(parents=True, exist_ok=True)
    (repo / ".factory" / "config" / "factory.yaml").write_text(config_text)
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", "kit")


def test_snapshot_is_made_from_committed_content_and_shared_by_equal_content(repo, tmp_path):
    commit_kit(repo)
    home = tmp_path / "home"
    h1 = gitops.snapshot_kit(repo, "HEAD", home)
    h2 = gitops.snapshot_kit(repo, "HEAD", home)
    assert h1 == h2 and (home / "kits" / h1 / "factory" / "workflows" / "bug-fix.yaml").is_file()
    assert (home / "kits" / h1 / ".factory" / "config" / "factory.yaml").is_file()
    assert [p.name for p in (home / "kits").iterdir()] == [h1]  # one folder for the same content


def test_snapshot_is_unchanged_when_the_main_checkout_is_edited_afterwards(repo, tmp_path):
    commit_kit(repo)
    home = tmp_path / "home"
    h = gitops.snapshot_kit(repo, "HEAD", home)
    before = (home / "kits" / h / "factory" / "workflows" / "bug-fix.yaml").read_text()
    (repo / "factory" / "workflows" / "bug-fix.yaml").write_text("name: CHANGED in the working tree\n")  # uncommitted edit
    (repo / ".factory" / "config" / "factory.yaml").write_text("base_branch: develop\n")
    assert (home / "kits" / h / "factory" / "workflows" / "bug-fix.yaml").read_text() == before
    # a new snapshot from the same committed content is the same folder: the edit was not committed
    assert gitops.snapshot_kit(repo, "HEAD", home) == h


def test_a_committed_change_to_the_kit_gives_a_different_snapshot(repo, tmp_path):
    commit_kit(repo)
    home = tmp_path / "home"
    h1 = gitops.snapshot_kit(repo, "HEAD", home)
    commit_kit(repo, workflow_text="name: bug-fix\nsink: pull_request\n")
    h2 = gitops.snapshot_kit(repo, "HEAD", home)
    assert h1 != h2 and (home / "kits" / h1).is_dir() and (home / "kits" / h2).is_dir()  # the older run keeps its own


def test_snapshot_without_a_kit_says_to_commit_it(repo, tmp_path):
    with pytest.raises(FactoryError, match="no factory/"):
        gitops.snapshot_kit(repo, "HEAD", tmp_path / "home")


def _fake_run(run_id, branch):
    from factory_engine.types import Request, Run, Source
    src = Source("cli", "r", "t", "b", [], None, [])
    req = Request("r", src, "sha", "repo", "t", "bug", "explicit", None, [])
    return Run(run_id=run_id, repo="repo", repo_key="local/repo", repo_path=Path("."), request=req, workflow=None,
               branch=branch, worktree=Path("."), status="running", stage=None, stages=[], loops={}, attention=None,
               pr=None, signals=None, heartbeat="", kit_hash="x", infra_wait=None)


def test_conflict_signals_count_commits_behind_and_name_overlapping_runs(repo, cfg):
    gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    rw2 = gitops.create_run_worktree(repo, cfg, "run-2", base="main", detached=False)
    rw1 = Path(cfg.machine["worktree_root"]) / "repo" / "run-1"
    for rw, text in ((rw1, "x = 'one'\n"), (rw2, "x = 'two'\n")):  # both change the same file
        (rw / "services" / "api.py").write_text(text)
        run(rw, "add", "-A"); run(rw, "commit", "-q", "-m", "change")
    (repo / "web" / "app.js").write_text("y = 'base moved'\n")
    run(repo, "add", "-A"); run(repo, "commit", "-q", "-m", "base moved"); run(repo, "push", "-q", "origin", "main")
    sig = gitops.conflict_signals(repo, _fake_run("run-1", "run-1"), [_fake_run("run-2", "run-2")], "main")
    assert sig.behind_base == 1
    assert sig.overlaps == [("run-2", ["services/api.py"])]


def test_conflict_signals_have_no_overlap_when_files_differ(repo, cfg):
    gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    rw2 = gitops.create_run_worktree(repo, cfg, "run-2", base="main", detached=False)
    rw1 = Path(cfg.machine["worktree_root"]) / "repo" / "run-1"
    (rw1 / "services" / "api.py").write_text("x = 'one'\n")
    (rw2 / "web" / "app.js").write_text("y = 'two'\n")
    for rw in (rw1, rw2):
        run(rw, "add", "-A"); run(rw, "commit", "-q", "-m", "change")
    sig = gitops.conflict_signals(repo, _fake_run("run-1", "run-1"), [_fake_run("run-2", "run-2")], "main")
    assert sig.overlaps == []


def _gate_ctx(tw, base, scope, deny):
    run_ = _fake_run("run-1", "run-1")
    from factory_engine.config import Config
    return GateContext(run=run_, stage="fix", task_id="a", worktree=tw, task_dir=None, artifact=None,
                       task_base=base, scope=scope, deny=deny, cfg=Config(machine={}, repo={}))


def test_scope_gate_fails_outside_scope_and_inside_deny_and_passes_otherwise(repo, cfg):
    gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    t = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'in scope'\n", "web/app.js": "y = 'outside'\n"})
    tw = Path(cfg.machine["worktree_root"]) / "repo" / "run-1--a"
    spec = GateSpec(kind="check", cmd=None, check="scope-diff", schema=None, args={})
    bad = gitops.check_scope_diff(spec, _gate_ctx(tw, t.task_base, ["services/**"], []))
    assert not bad.passed and bad.details["files"] == ["web/app.js"]
    # a deny path added later by a note (it arrives in ctx.deny) fails a file that was in scope
    denied = gitops.check_scope_diff(spec, _gate_ctx(tw, t.task_base, ["services/**", "web/**"], ["services/api.py"]))
    assert not denied.passed and denied.details["files"] == ["services/api.py"]
    ok = gitops.check_scope_diff(spec, _gate_ctx(tw, t.task_base, ["services/**", "web/**"], []))
    assert ok.passed


def test_the_engine_pushes_only_the_run_branch_and_nothing_else_reaches_the_remote(repo, cfg):
    rw = gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    t = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    assert gitops.join(rw, [t], regenerate=[], join_cmd=None).ok
    gitops.push(rw, "run-1")
    assert sorted(r for r in ls_remote(repo) if r != "HEAD") == ["refs/heads/main", "refs/heads/run-1"]
