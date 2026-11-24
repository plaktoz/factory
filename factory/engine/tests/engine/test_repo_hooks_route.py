"""Module 17A, "Where lint and format run": repo hooks run on the join commit and before push, a failing hook routes to
rework, and checkpoint commits skip hooks. Each route is driven through the engine on a real temp git repo with a real
hook script, so the test fails when the routing (module 6B, module 8) or the hook (module 7) does."""

import json

from factory_engine import gitops, state
from factory_engine.adapters.worker.fake import ok

from engine_helpers import chore_script


def _install_hook(repo, name, script):
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / name).write_text(f"#!/bin/sh\n{script}\n")
    (hooks / name).chmod(0o755)


def _plant_in_change(worker, rel, text):
    real_start = worker.start

    def start(ctx, conf, log):
        if ctx.task_id == "change":
            (ctx.worktree / rel).parent.mkdir(parents=True, exist_ok=True)
            (ctx.worktree / rel).write_text(text)
        return real_start(ctx, conf, log)

    worker.start = start


def test_a_failing_repo_hook_on_the_join_commit_routes_the_run_back_to_implement(new_run, engine, repo):
    """The join commit runs the repo's pre-commit hook. A hook that always fails is rework: the stage's on_fail edge
    sends the run back to `implement`, and the run branch returns to its pre-join commit. The hook's own output is
    not in the feedback record yet (JoinResult carries no hook output; that is left for the owner)."""
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * 4)
    eng, worker = engine(script, writes)
    _plant_in_change(worker, "services/new.py", "x = 2\n")
    _install_hook(repo, "pre-commit", "echo 'lint: services/new.py line 1' >&2\nexit 1")
    eng.run(["bump-q1w2e"])
    run = state.read_run(run_dir)
    routed = [e for e in state.read_events(run_dir) if e.type == "routed_back"]
    assert routed and routed[0].data["from_stage"] == "implement" and routed[0].data["to_stage"] == "implement"
    assert run.loops["implement->implement"] >= 1
    feedback = sorted((run_dir / "tasks" / "change" / "feedback").glob("*.json"))
    assert feedback and "a repo hook failed on the join commit" in feedback[-1].read_text()
    base = gitops.git(repo, "rev-parse", "main").stdout.strip()
    assert gitops.git(run.worktree, "rev-parse", "HEAD").stdout.strip() == base  # the failed join was undone


def test_checkpoints_skip_the_pre_commit_hook_and_only_the_join_runs_it(new_run, engine, repo):
    """A checkpoint is `git commit --no-verify` in the task worktree, so the shared pre-commit hook never runs there.
    The hook records the worktree it ran in. Only the run worktree (the join) may appear, never the task's."""
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * 4)
    eng, worker = engine(script, writes)
    _plant_in_change(worker, "services/new.py", "x = 2\n")
    log = repo.parent / "hook-ran.log"
    _install_hook(repo, "pre-commit", f"basename \"$PWD\" >> {log}\nexit 0")
    eng.run(["bump-q1w2e"])
    ran_in = log.read_text().splitlines() if log.exists() else []
    task_worktree = "bump-q1w2e--change"
    assert task_worktree not in ran_in          # the checkpoint in the task worktree skipped the hook
    assert "bump-q1w2e" in ran_in                # the join in the run worktree ran it


def test_every_worktree_the_engine_creates_has_the_run_marker_and_no_other_factory_file(new_run, engine, repo):
    """Module 7: each worktree the engine creates holds `.factory-run.json` pointing to the run folder, excluded from git,
    and no factory file other than the shims. Checked on the run worktree and on a task worktree, after a real run."""
    import json
    from factory_engine import gitops as g
    run_dir = new_run()
    script, writes = chore_script(run_dir)
    eng, worker = engine(script, writes)
    seen: dict[str, Path] = {}
    real_start = worker.start

    def start(ctx, conf, log):  # a clean run removes its task worktrees after the join, so look while the worker runs
        if ctx.task_id == "change":
            seen["task"] = ctx.worktree
            seen["task_state"] = _snapshot(ctx.worktree, g)
        return real_start(ctx, conf, log)

    worker.start = start
    eng.run(["bump-q1w2e"])
    run = state.read_run(run_dir)
    snapshots = {"run": _snapshot(run.worktree, g), "task": seen["task_state"]}
    for name, snap in snapshots.items():
        assert snap["marker_run_dir"] == str(run_dir), f"the {name} worktree marker does not point to the run folder"
        assert snap["status"] == "", f"the {name} worktree shows the marker as a git change: {snap['status']}"
        assert snap["factory_files"] == [g.RUN_MARKER], f"the {name} worktree holds {snap['factory_files']}"


def _snapshot(wt, g):
    marker = wt / g.RUN_MARKER
    return {"marker_run_dir": json.loads(marker.read_text())["run_dir"] if marker.is_file() else None,
            "status": g.git(wt, "status", "--porcelain").stdout.strip(),
            "factory_files": sorted(p.name for p in wt.iterdir() if p.name.startswith(".factory"))}


def test_a_failing_pre_push_hook_routes_the_run_back_to_rework_and_does_not_crash_the_tick(new_run, engine, repo):
    """Before push the repo's pre-push hook runs. A hook that always fails is rework (module 8): the run goes back to the
    stage's on_fail edge, and the tick returns instead of raising. The run must not be left failed with an error."""
    from gitutil import ls_remote
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    # The push fails on every pass, so the run loops back through `implement` and `verify` until the loop maximum: the
    # scripted attempts cover that (each loop runs `change` and `check` once more).
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * 4,
                                  check=[ok(work("check", "check.log"))] * 4)
    eng, worker = engine(script, writes)
    _plant_in_change(worker, "services/new.py", "x = 2\n")
    _install_hook(repo, "pre-push", "echo 'pre-push: blocked by policy' >&2\nexit 1")
    result = eng.run(["bump-q1w2e"])
    run = state.read_run(run_dir)
    routed = [e for e in state.read_events(run_dir) if e.type == "routed_back"]
    assert routed, f"a failing pre-push hook was not routed back to rework: status={result.runs}"
    assert run.status != "failed"
    feedback = sorted((run_dir / "tasks" / "change" / "feedback").glob("*.json"))
    assert feedback and "blocked by policy" in feedback[-1].read_text()  # the hook's output reaches the worker
    assert not any(r == "refs/heads/bump-q1w2e" for r in ls_remote(repo))  # nothing reached the remote
