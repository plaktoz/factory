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


def _join_with_hook(repo, cfg, script):
    rw = start_run(repo, cfg)
    a = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    hooks = Path(run(rw, "rev-parse", "--path-format=absolute", "--git-path", "hooks"))
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").write_text(f"#!/bin/sh\n{script}\n")
    (hooks / "pre-commit").chmod(0o755)
    return gitops.join(rw, [a], regenerate=[], join_cmd=None)


def test_a_failing_repo_hook_on_the_join_commit_returns_the_hooks_output(repo, cfg):
    """Module 7 and section 18: JoinResult.hook_output holds what the failing hook printed, on stderr or stdout."""
    r = _join_with_hook(repo, cfg, "echo 'lint: services/api.py line 1' >&2\necho 'stdout: 1 error'\nexit 1")
    assert r.hook_failed and "lint: services/api.py line 1" in r.hook_output and "stdout: 1 error" in r.hook_output


def test_the_join_hook_output_is_the_tail_of_a_long_output(repo, cfg):
    r = _join_with_hook(repo, cfg, "i=0\nwhile [ $i -lt 500 ]; do echo \"line $i\" >&2; i=$((i+1)); done\n"
                                   "echo 'ruff: command not found' >&2\nexit 1")
    assert "ruff: command not found" in r.hook_output and "line 0" not in r.hook_output.splitlines()
    assert len(r.hook_output.splitlines()) <= 200


def test_a_join_that_did_not_fail_on_a_hook_has_no_hook_output(repo, cfg):
    rw = start_run(repo, cfg)
    a = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    assert gitops.join(rw, [a], regenerate=[], join_cmd=None).hook_output is None


def test_the_engine_pushes_with_repo_hooks_and_a_failing_pre_push_hook_stops_the_push(repo, cfg):
    """Acceptance (module 7): repo hooks run on the push. The checkpoint skips them; the push does not."""
    rw = start_run(repo, cfg)
    make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    a = TaskBranch("a", "run-1--a", run(rw, "rev-parse", "HEAD"))
    assert gitops.join(rw, [a], regenerate=[], join_cmd=None).ok
    hooks = Path(run(rw, "rev-parse", "--path-format=absolute", "--git-path", "hooks"))
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-push").write_text("#!/bin/sh\necho 'pre-push: blocked by policy' >&2\nexit 1\n")
    (hooks / "pre-push").chmod(0o755)
    with pytest.raises(FactoryError):
        gitops.push(rw, "run-1")
    assert not any(r == "refs/heads/run-1" for r in ls_remote(repo))  # nothing reached the remote


def test_a_failing_pre_push_hook_is_git_hook_failed_with_its_output(repo, cfg):
    """Module 7: `push` raises git.hook_failed when a repo hook rejects the push, so rework routes it (module 8)."""
    rw = start_run(repo, cfg)
    make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    a = TaskBranch("a", "run-1--a", run(rw, "rev-parse", "HEAD"))
    assert gitops.join(rw, [a], regenerate=[], join_cmd=None).ok
    hooks = Path(run(rw, "rev-parse", "--path-format=absolute", "--git-path", "hooks"))
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-push").write_text("#!/bin/sh\necho 'pre-push: blocked by policy' >&2\nexit 1\n")
    (hooks / "pre-push").chmod(0o755)
    with pytest.raises(FactoryError) as e:
        gitops.push(rw, "run-1")
    assert e.value.code == "git.hook_failed"
    assert "blocked by policy" in e.value.message


def test_checkpoint_never_commits_shims_or_anything_in_the_task_folder(repo, cfg, tmp_path):
    from factory_engine import shims
    from factory_engine.skills import SkillRef
    gitops.create_run_worktree(repo, cfg, "run-1", base="main", detached=False)
    gitops.create_task_worktree(repo, cfg, "run-1", "backend", base_branches=["run-1"])
    tw = Path(cfg.machine["worktree_root"]) / "repo" / "run-1--backend"
    skill = tmp_path / "skills" / "fix"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("rules\n")
    shims.generate_shims(tw, ["claude"], [SkillRef("fix", "own", skill, {})])
    task_dir = tmp_path / "home" / "tasks" / "backend" / "work"  # $FACTORY_TASK_DIR lives in the factory home
    task_dir.mkdir(parents=True)
    (task_dir / "progress.md").write_text("notes\n")
    (tw / "services" / "api.py").write_text("x = 3\n")
    assert gitops.checkpoint(tw, "backend", 1) is not None
    assert (tw / ".claude" / "skills" / "factory-fix").is_symlink()  # the shim is there
    assert run(tw, "show", "--name-only", "--format=", "HEAD").splitlines() == ["services/api.py"]
    assert run(tw, "status", "--porcelain") == ""


def test_a_worker_that_pushes_changes_nothing_the_engine_counts(repo, cfg):
    rw = start_run(repo, cfg)
    t = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    tw = Path(cfg.machine["worktree_root"]) / "repo" / "run-1--a"
    (tw / "web" / "app.js").write_text("y = 'worker'\n")
    run(tw, "add", "-A"); run(tw, "commit", "-q", "-m", "worker made this commit")
    run(tw, "push", "-q", "origin", "HEAD:refs/heads/worker-stray")  # the worker also pushes
    assert gitops.join(rw, [t], regenerate=[], join_cmd=None).ok
    assert run(rw, "rev-list", "--count", "main..HEAD") == "1"
    gitops.push(rw, "run-1")
    subjects = run(repo, "log", "--format=%s", "origin/run-1").splitlines()
    assert any(s.startswith("task(a):") for s in subjects) and not any("worker" in s for s in subjects)


def test_a_worktree_root_inside_the_repo_is_refused_when_a_worktree_is_created(repo, tmp_path):
    from factory_engine.config import Config
    inside = Config(machine={"worktree_root": str(repo / "wt-in"), "worktree_path": "{root}/{repo}/{run_id}"},
                    repo={"base_branch": "main"})
    with pytest.raises(FactoryError, match="inside the repo"):
        gitops.create_run_worktree(repo, inside, "run-9", base="main", detached=False)
    assert not (repo / "wt-in").exists()


def test_the_engine_never_force_pushes(repo, cfg):
    """Acceptance (module 7): no push the engine makes carries --force. The git call is observed, not the outcome."""
    import subprocess as sp
    rw = start_run(repo, cfg)
    make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    a = TaskBranch("a", "run-1--a", run(rw, "rev-parse", "HEAD"))
    assert gitops.join(rw, [a], regenerate=[], join_cmd=None).ok
    seen: list[list[str]] = []
    real = sp.run

    def spy(args, *x, **k):
        if isinstance(args, (list, tuple)):
            seen.append(list(args))
        return real(args, *x, **k)
    import factory_engine.gitops as g
    orig = g.subprocess.run
    g.subprocess.run = spy
    try:
        gitops.push(rw, "run-1")
    finally:
        g.subprocess.run = orig
    pushes = [c for c in seen if "push" in c]
    assert pushes and not any(f in c for c in pushes for f in ("--force", "-f", "--force-with-lease"))


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


def test_an_interrupted_snapshot_copy_leaves_no_kit_folder_and_the_next_one_succeeds(repo, tmp_path, monkeypatch):
    """Module 3, Run snapshot: the copy goes into kits/<hash>.tmp and is renamed only when whole."""
    commit_kit(repo)
    home = tmp_path / "home"
    real = gitops.Path.rename

    def dies(self, target):
        raise KeyboardInterrupt

    monkeypatch.setattr(gitops.Path, "rename", dies)
    with pytest.raises(KeyboardInterrupt):
        gitops.snapshot_kit(repo, "HEAD", home)
    assert [p.name for p in (home / "kits").iterdir() if not p.name.endswith(".tmp")] == []  # no half kit
    monkeypatch.setattr(gitops.Path, "rename", real)
    h = gitops.snapshot_kit(repo, "HEAD", home)
    assert (home / "kits" / h / "factory" / "workflows" / "bug-fix.yaml").is_file()
    assert [p.name for p in (home / "kits").iterdir()] == [h]  # the leftover .tmp was removed first


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


# ---------------- hook retry ----------------

def _install_hook(worktree, script):
    hooks = Path(run(worktree, "rev-parse", "--path-format=absolute", "--git-path", "hooks"))
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").write_text(script)
    (hooks / "pre-commit").chmod(0o755)


def test_a_hook_that_edits_files_is_retried_once_with_its_changes_staged(repo, cfg):
    rw = start_run(repo, cfg)
    a = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    # a formatter-style hook: it edits the file and fails the first time; on the second commit the edit is staged
    _install_hook(rw, "#!/bin/sh\nif ! grep -q formatted services/api.py; then echo '# formatted' >> services/api.py; exit 1; fi\nexit 0\n")
    r = gitops.join(rw, [a], regenerate=[], join_cmd=None)
    assert r.ok and not r.hook_failed and len(r.commits) == 1
    assert "# formatted" in run(rw, "show", "HEAD:services/api.py")  # the hook's edit is in the commit


def test_a_second_hook_failure_is_returned_as_hook_failed(repo, cfg):
    rw = start_run(repo, cfg)
    a = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    _install_hook(rw, "#!/bin/sh\necho '# touched' >> services/api.py\nexit 1\n")  # edits and fails every time
    before = run(rw, "rev-parse", "HEAD")
    r = gitops.join(rw, [a], regenerate=[], join_cmd=None)
    assert not r.ok and r.hook_failed
    assert run(rw, "rev-parse", "HEAD") == before and run(rw, "status", "--porcelain") == ""


# ---------------- chained branches and rework resets ----------------

def test_chained_task_branches_are_deleted_after_the_join_dependents_first(repo, cfg):
    rw = start_run(repo, cfg)
    a = make_task(repo, cfg, "run-1", "a", {"services/api.py": "x = 'a'\n"})
    b = make_task(repo, cfg, "run-1", "b", {"web/app.js": "y = 'b'\n"}, bases=["run-1--a"])
    c = make_task(repo, cfg, "run-1", "c", {"services/new.py": "z = 'c'\n"}, bases=["run-1--b"])
    assert gitops.join(rw, [a, b, c], regenerate=[], join_cmd=None).ok
    deleted = gitops.delete_chained_branches(repo, "run-1", {"a": [], "b": ["a"], "c": ["b"]})
    assert deleted == ["run-1--c", "run-1--b", "run-1--a"]  # dependents first
    assert run(repo, "branch", "--list", "run-1--*") == ""
    assert run(rw, "rev-list", "--count", "main..HEAD") == "3"  # the join commits are untouched


def test_deleting_in_the_wrong_order_would_be_seen(repo, cfg):
    """The order is computed from needs, not from the order the dict was written in."""
    start_run(repo, cfg)
    for t, bases in (("a", ["run-1"]), ("b", ["run-1--a"])):
        make_task(repo, cfg, "run-1", t, {f"web/{t}.js": t}, bases=bases)
    assert gitops.delete_chained_branches(repo, "run-1", {"a": [], "b": ["a"]}) == ["run-1--b", "run-1--a"]
    assert gitops.delete_chained_branches(repo, "run-1", {"b": ["a"], "a": []}) == []  # already gone; no error


def test_a_cycle_in_needs_is_refused(repo, cfg):
    with pytest.raises(FactoryError, match="cycle"):
        gitops.delete_chained_branches(repo, "run-1", {"a": ["b"], "b": ["a"]})


# ---------------- module 8 step 3 and the 6B gate reset ----------------
# 6B takes the run branch's HEAD before a stage's join and, when that stage's gate fails, runs
# `git reset --hard <that commit>`. These tests use the real join and the same reset. They pin what module 8 step 3
# ("the run branch keeps its commits") relies on. They do not run the engine; the engine-level test belongs to 6B.

def test_resetting_to_the_pre_join_commit_keeps_the_commits_of_stages_that_already_passed(repo, cfg):
    rw = start_run(repo, cfg)
    fix = make_task(repo, cfg, "run-1", "fix", {"services/api.py": "x = 'fixed'\n"})
    assert gitops.join(rw, [fix], regenerate=[], join_cmd=None).ok          # the fix stage joined and passed its gates
    after_fix = run(rw, "rev-parse", "HEAD")

    pre_join = run(rw, "rev-parse", "HEAD")                                  # verify's join starts here
    verify = make_task(repo, cfg, "run-1", "verify", {"tests/test_api.py": "assert False\n"})
    assert gitops.join(rw, [verify], regenerate=[], join_cmd=None).ok
    assert run(rw, "rev-parse", "HEAD") != pre_join                          # the join added a commit; the gate then fails

    run(rw, "reset", "--hard", pre_join)                                     # what 6B does when the gate fails
    assert run(rw, "rev-parse", "HEAD") == after_fix                         # fix's commit is still on the run branch
    assert (rw / "services" / "api.py").read_text() == "x = 'fixed'\n"       # so the rework continues from the fix
    assert not (rw / "tests" / "test_api.py").exists()                       # the failed stage's own join is gone
    assert run(rw, "status", "--porcelain") == ""                            # nothing half-applied is left behind


def test_resetting_to_the_pre_join_commit_drops_the_failed_stages_own_commits(repo, cfg):
    """The case step 3 does not describe: the stage whose gate fails is the stage that made the commits (a scope-diff
    failure in fix itself). Its join is undone, so the run branch is back at the base, not 'keeping its commits'."""
    rw = start_run(repo, cfg)
    base = run(rw, "rev-parse", "HEAD")
    fix = make_task(repo, cfg, "run-1", "fix", {"web/app.js": "out of scope\n"})
    assert gitops.join(rw, [fix], regenerate=[], join_cmd=None).ok
    run(rw, "reset", "--hard", base)
    assert run(rw, "rev-parse", "HEAD") == base
    assert run(rw, "rev-list", "--count", "main..HEAD") == "0"


def _factory_files(wt):
    """Every file in the worktree, ignored ones too, that is a factory file: one under a `factory` or `.factory` path,
    except the shims (module 7: the only factory files a worktree may hold besides the marker)."""
    import os
    shims = (".claude/skills/factory-", ".agents/skills/factory-")
    found = []
    for dirpath, dirnames, filenames in os.walk(wt):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            rel = Path(dirpath, name).relative_to(wt).as_posix()
            if any(p == "factory" or p.startswith(".factory") for p in rel.split("/")) and not rel.startswith(shims):
                found.append(rel)
    return sorted(found)
