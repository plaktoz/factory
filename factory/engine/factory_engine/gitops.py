"""Git operations (module 7): worktrees, checkpoints, changed files, the scope check.

Every git action runs as an argument list with no shell (module 7). The engine is the only committer
(commit authority): workers edit files and never run git commit or push.
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
from pathlib import Path

from .config import Config
from .types import GateContext, GateResult, GateSpec, JoinResult, Run, Signals, SyncResult, TaskBranch
from .errors import FactoryError
from .paths import check_not_existing, check_outside_repo, render

RUN_MARKER = ".factory-run.json"
# Paths the engine never commits: the task's work folder and the generated shims (module 7).
NEVER_COMMITTED = (".factory-run.json", ".claude/skills/factory-", ".agents/skills/factory-")


def git(repo: Path, *args: str, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run git with an argument list. A failure raises the catalogue code that matches its stderr (module 7)."""
    cmd = ["git", "-C", str(repo), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        code, hint = _classify(r.stderr, args)
        raise FactoryError(code, f"git {' '.join(args[:2])}: {r.stderr.strip()[:300]}", hint=hint)
    return r


def _classify(stderr: str, args: tuple[str, ...]) -> tuple[str, str]:
    """Map git's stderr to a catalogue code. A message that matches no row is not hidden under a catch-all."""
    if "index.lock" in stderr:
        return "git.index_locked", "another git process holds the index; the engine retries with backoff"
    if "contains modified or untracked files" in stderr:
        return "git.worktree_dirty", "show the changed files; remove the worktree only after the check passes"
    if "already exists" in stderr:
        return "git.path_exists", "remove the existing path or use a new run id"
    if args[:1] == ("push",) and _hook_stopped_push(stderr):
        return "git.hook_failed", "show the hook output; a failing repo hook is rework (module 8)"
    if "rejected" in stderr and args[:1] == ("push",):
        return "git.push_rejected", "base sync and one retry have run; a person must look at this"
    if "Authentication" in stderr or "authentication" in stderr or "gh auth login" in stderr:
        return "git.auth_expired", "run gh auth login, then retry"
    return "git.command_failed", "run the same git command by hand to reproduce it"


def _hook_stopped_push(stderr: str) -> bool:
    """A pre-push hook that exits non-zero ends the push before any ref is sent, so git prints the hook's output and
    `failed to push some refs` with no ` ! [...]` ref-status line. A remote refusal or a non-fast-forward has that line."""
    return "failed to push some refs" in stderr and not any(line.lstrip().startswith("! [") for line in stderr.splitlines())


def _commit_args(message: str) -> list[str]:
    # Checkpoint and join commits skip repo hooks only where the spec says so (module 7): this is the checkpoint form.
    return ["-c", "user.name=factory", "-c", "user.email=factory@local", "commit", "--no-verify", "-m", message]


def mark_run(worktree: Path, run_dir: Path, run_id: str, repo_key: str) -> None:
    """Write .factory-run.json at the worktree root and exclude it from git (module 3, module 7)."""
    (worktree / RUN_MARKER).write_text(json.dumps({"run_id": run_id, "repo_key": repo_key, "run_dir": str(run_dir)},
                                                  indent=2) + "\n")
    _exclude(worktree, RUN_MARKER)


def _exclude(worktree: Path, pattern: str) -> None:
    info = Path(git(worktree, "rev-parse", "--git-path", "info/exclude").stdout.strip())
    if not info.is_absolute():
        info = worktree / info
    info.parent.mkdir(parents=True, exist_ok=True)
    existing = info.read_text().splitlines() if info.exists() else []
    if pattern not in existing:
        info.write_text("\n".join(existing + [pattern]) + "\n")


def create_run_worktree(repo: Path, cfg: Config, run_id: str, *, base: str, detached: bool) -> Path:
    """Module 7: `git worktree add -b <run> <path> origin/<base>`, or detached for a read-only run.

    The path is rendered from the config (worktree_path, module 3); it must not exist and must be outside the repo."""
    path = _worktree_for(repo, cfg, run_id, None)
    check_not_existing(path)
    check_outside_repo(path, repo)
    git(repo, "fetch", "--quiet", "origin", check=False)
    start = f"origin/{base}" if _has_ref(repo, f"origin/{base}") else base
    if detached:
        git(repo, "worktree", "add", "--detach", str(path), start)
    else:
        git(repo, "worktree", "add", "-b", run_id, str(path), start)
    return path


def _has_ref(repo: Path, ref: str) -> bool:
    return git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0


def base_ref(repo: Path, base: str) -> str:
    """The base a run is compared with: origin/<base> when it exists, else the local <base>."""
    return f"origin/{base}" if _has_ref(repo, f"origin/{base}") else base


def create_delivery_branch(worktree: Path, run_id: str) -> None:
    """A read-only run gets its branch only at delivery (module 7): `git switch -c <run>`."""
    git(worktree, "switch", "-c", run_id)


def create_task_worktree(repo: Path, cfg: Config, run_id: str, task_id: str, *,
                         base_branches: list[str] | None = None) -> Path:
    """Module 7: `git worktree add -b <run>--<task> <path> <base>`.

    The base is the run branch when the task has no dependency, the dependency's branch when it has one, and for
    several dependencies the first one with the others merged in (module 7). `base_branches` lists them in needs order."""
    path = _worktree_for(repo, cfg, run_id, task_id)
    check_not_existing(path)
    check_outside_repo(path, repo)
    bases = base_branches or [run_id]
    base = bases[0]
    git(repo, "worktree", "add", "-b", f"{run_id}--{task_id}", str(path), base)
    for other in bases[1:]:
        wt = path
        git(wt, "-c", "user.name=factory", "-c", "user.email=factory@local", "merge", "--no-edit", other)
    return path


def _worktree_for(repo: Path, cfg: Config, run_id: str, task_id: str | None) -> Path:
    template = (cfg.machine or {}).get("worktree_path", "{root}/{repo}/{run_id}")
    root = Path((cfg.machine or {}).get("worktree_root") or Path.home() / ".factory" / "worktrees")
    return render(template, root=root, repo=repo.name, owner="", run_id=run_id, task=task_id)


def checkpoint(worktree: Path, task_id: str, n: int) -> str | None:
    """Commit the product files the task changed, as `wip(<task>): checkpoint <n>`, on the local task branch.

    Returns the new commit's sha, or None when nothing changed. Checkpoints skip repo hooks (--no-verify) and never
    format code. Files the engine keeps out of commits (the marker, shims) are never staged (module 7, criteria)."""
    git(worktree, "add", "-A")
    for path in NEVER_COMMITTED:
        git(worktree, "reset", "-q", "--", path, check=False)
    if git(worktree, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return None
    git(worktree, *_commit_args(f"wip({task_id}): checkpoint {n}"))
    return git(worktree, "rev-parse", "HEAD").stdout.strip()


def changed_files(worktree: Path, base_ref: str) -> list[str]:
    """Files that differ from base_ref to HEAD, as the scope check reads them (module 7)."""
    out = git(worktree, "diff", "--name-only", f"{base_ref}...HEAD").stdout
    return [line for line in out.splitlines() if line]


def task_changed_files(worktree: Path, base_ref: str | None) -> list[str]:
    """Every file the task changed: committed since its base, plus edits and new files not yet committed. Files the
    engine keeps out of commits are left out (module 17A formats these once, after the worker stops)."""
    committed = changed_files(worktree, base_ref) if base_ref else []
    out = git(worktree, "status", "--porcelain", "-uall", "-z").stdout.split("\0")
    pending: list[str] = []
    i = 0
    while i < len(out):
        e = out[i]
        i += 1
        if len(e) < 4:
            continue
        status, path = e[:2], e[3:]
        if "R" in status or "C" in status:
            i += 1  # under -z a rename or copy is followed by its source path, which is not a changed file
        if "D" not in status:
            pending.append(path)
    return sorted({f for f in [*committed, *pending] if not any(f.startswith(n) for n in NEVER_COMMITTED)})


def check_scope_diff_paths(files: list[str], scope: list[str], deny: list[str]) -> list[str]:
    """Module 7 check: returns the files that are out of scope or inside a deny glob. Empty means the check passes.
    Deny globs always win over scope globs."""
    bad = []
    for f in files:
        if any(fnmatch.fnmatch(f, d) for d in deny):
            bad.append(f)
        elif scope and not any(fnmatch.fnmatch(f, s) for s in scope):
            bad.append(f)
    return bad


def remove_worktree(path: Path, *, force: bool = False) -> None:
    """Module 7: `git worktree remove <path>`, run from the worktree's own common repository, so the caller
    does not need to name the repo. A worktree that is not clean is refused unless force is set."""
    common = Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    repo = common.parent if common.name == ".git" else common
    args = ["worktree", "remove"] + (["--force"] if force else []) + [str(path)]
    git(repo, *args)


def delete_branch(repo: Path, name: str, *, remote: bool = False) -> None:
    """Module 7: `git branch -D`. A remote delete is never done by the engine for task branches (they are never pushed)."""
    if remote:
        raise FactoryError("git.command_failed", "the engine does not delete remote task branches",
                           hint="task branches are never pushed, so there is no remote branch to delete")
    git(repo, "branch", "-D", name)


def _task_diff(worktree: Path, task_base: str, branch: str, regenerate: list[str] | None = None) -> str:
    """The change a task made: its diff from its base to its tip (module 7). The base of a chained task is its
    dependency's branch, so the dependency's change is not in this diff and is never applied twice.

    Files listed in `regenerate` are left out of the diff: the spec drops task edits to lockfiles and generated code
    and rebuilds them once with join_cmd, so two tasks that both edit a lockfile never conflict on it."""
    exclude = [f":(exclude){path}" for path in (regenerate or [])]
    return git(worktree, "diff", "--binary", f"{task_base}...{branch}", "--", ".", *exclude).stdout


def join(run_worktree: Path, tasks: list[TaskBranch], *, regenerate: list[str],
         join_cmd: list[str] | None) -> JoinResult:
    """Apply each task's own change to the run branch, in `needs` order, one commit per task (module 7).

    On a conflict the worktree is reset to its last good commit and the conflicting files are returned, not raised.
    Files in `regenerate` (lockfiles, generated code) are dropped from each task's diff and rebuilt once by
    join_cmd after the last task. A repo hook that fails on a task commit returns hook_failed."""
    commits: list[str] = []
    start = git(run_worktree, "rev-parse", "HEAD").stdout.strip()
    for task in tasks:
        diff = _task_diff(run_worktree, task.task_base, task.branch, regenerate)
        if not diff.strip():
            continue
        patch = run_worktree / f".join-{task.task_id}.patch"
        patch.write_text(diff)
        try:
            r = git(run_worktree, "apply", "--3way", "--index", str(patch), check=False)
        finally:
            patch.unlink(missing_ok=True)
        if r.returncode != 0 or _unmerged(run_worktree):
            conflicts = _unmerged(run_worktree)
            git(run_worktree, "reset", "--hard", start, check=False)
            git(run_worktree, "clean", "-fd", "-e", ".factory-run.json", check=False)
            return JoinResult(ok=False, conflict_files=conflicts, hook_failed=False, commits=[])
        r = _commit_with_hook_retry(run_worktree, f"task({task.task_id}): joined from {task.branch}")
        if r.returncode != 0:
            git(run_worktree, "reset", "--hard", start, check=False)
            return JoinResult(ok=False, conflict_files=[], hook_failed=True, commits=[])
        commits.append(git(run_worktree, "rev-parse", "HEAD").stdout.strip())
    if join_cmd and regenerate:
        r = subprocess.run(join_cmd, cwd=run_worktree, capture_output=True, text=True)
        if r.returncode == 0:
            git(run_worktree, "add", "-A", *regenerate, check=False)
            git(run_worktree, "-c", "user.name=factory", "-c", "user.email=factory@local",
                "commit", "-m", "chore: regenerate lockfiles at join", check=False)
            commits.append(git(run_worktree, "rev-parse", "HEAD").stdout.strip())
    return JoinResult(ok=True, conflict_files=[], hook_failed=False, commits=commits)


def _commit_with_hook_retry(worktree: Path, message: str) -> subprocess.CompletedProcess:
    """Commit with the repo's hooks on. A hook that edits files (a formatter) fails the commit and leaves its edit
    unstaged; the spec retries once with that edit staged, and a second failure is returned as hook_failed (module 7)."""
    ident = ["-c", "user.name=factory", "-c", "user.email=factory@local"]
    r = git(worktree, *ident, "commit", "-m", message, check=False)
    if r.returncode == 0:
        return r
    git(worktree, "add", "-A", check=False)
    for path in NEVER_COMMITTED:
        git(worktree, "reset", "-q", "--", path, check=False)
    return git(worktree, *ident, "commit", "-m", message, check=False)


def _unmerged(worktree: Path) -> list[str]:
    out = git(worktree, "diff", "--name-only", "--diff-filter=U", check=False).stdout
    return [line for line in out.splitlines() if line]


def sync_base(run_worktree: Path, base: str) -> SyncResult:
    """Bring the run branch up to date with the base (module 7). A conflict is returned, and the branch is reset."""
    git(run_worktree, "fetch", "--quiet", "origin", check=False)
    target = f"origin/{base}" if _has_ref(run_worktree, f"origin/{base}") else base
    start = git(run_worktree, "rev-parse", "HEAD").stdout.strip()
    r = git(run_worktree, "-c", "user.name=factory", "-c", "user.email=factory@local", "merge", "--no-edit", target, check=False)
    if r.returncode != 0:
        conflicts = _unmerged(run_worktree)
        git(run_worktree, "merge", "--abort", check=False)
        git(run_worktree, "reset", "--hard", start, check=False)
        return SyncResult(ok=False, conflict_files=conflicts)
    return SyncResult(ok=True, conflict_files=[])


def push(worktree: Path, branch: str) -> None:
    """Push the run branch only (module 7). The engine never force-pushes and never pushes the base branch."""
    base = git(worktree, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False).stdout.strip().removeprefix("origin/")
    if branch in {"main", "master", base} or branch.startswith("origin/"):
        raise FactoryError("git.command_failed", f"refusing to push {branch}: the engine never pushes the base branch",
                           hint="the engine pushes only the run branch")
    git(worktree, "push", "-u", "origin", f"{branch}:{branch}")


def snapshot_kit(repo: Path, base_ref: str, home: Path) -> str:
    """Copy factory/ and .factory/config/ from the base branch's COMMITTED content into kits/<hash>/ (module 3, module 7).

    The content comes from `git archive` of base_ref, so a branch switch, a pull or an edit in the working tree
    cannot change it. The hash covers the copied files, so runs made from the same content share one folder."""
    import hashlib
    import io
    import shutil
    import tarfile

    paths = [p for p in ("factory", ".factory/config") if git(repo, "ls-tree", "-d", "--name-only", base_ref, p, check=False).stdout.strip()]
    if not paths:
        raise FactoryError("config.invalid", f"{base_ref} has no factory/ or .factory/config/ folder",
                           hint="commit the kit with factory init, then retry")
    archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", base_ref, *paths], capture_output=True)
    if archive.returncode != 0:
        raise FactoryError("git.command_failed", f"git archive failed: {archive.stderr.decode()[:300]}",
                           hint="check that the base ref exists and is committed")
    digest = hashlib.sha256()
    members: list[tuple[str, bytes]] = []
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        for m in sorted(tar.getmembers(), key=lambda m: m.name):
            if m.isfile():
                data = tar.extractfile(m).read()  # type: ignore[union-attr]
                members.append((m.name, data))
                digest.update(m.name.encode() + b"\0" + data + b"\0")
    kit_hash = digest.hexdigest()[:12]
    dest = home / "kits" / kit_hash
    if not dest.exists():
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        for name, data in members:
            out = tmp / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
        tmp.rename(dest)
    return kit_hash


def conflict_signals(repo: Path, run: Run, others: list[Run], base: str) -> Signals:
    """How far the run is behind the base, and which other active runs change the same files (module 7)."""
    ref = f"origin/{base}" if _has_ref(repo, f"origin/{base}") else base
    behind = 0
    if run.branch and _has_ref(repo, run.branch):
        behind = int(git(repo, "rev-list", "--count", f"{run.branch}..{ref}").stdout.strip() or 0)
    mine = _files_changed_by(repo, run.branch, ref) if run.branch else set()
    overlaps: list[tuple[str, list[str]]] = []
    for other in others:
        if other.run_id == run.run_id or not other.branch or not _has_ref(repo, other.branch):
            continue
        shared = sorted(mine & _files_changed_by(repo, other.branch, ref))
        if shared:
            overlaps.append((other.run_id, shared))
    return Signals(behind_base=behind, overlaps=overlaps)


def _files_changed_by(repo: Path, branch: str, base_ref: str) -> set[str]:
    if not _has_ref(repo, branch):
        return set()
    out = git(repo, "diff", "--name-only", f"{base_ref}...{branch}", check=False).stdout
    return {line for line in out.splitlines() if line}


def check_scope_diff(spec: GateSpec, ctx: GateContext) -> GateResult:
    """The scope-diff gate (module 7, used by module 8): every changed file must be inside the task's scope and
    outside its deny paths, including deny paths added by notes (they arrive in ctx.deny)."""
    files = changed_files(ctx.worktree, ctx.task_base or "HEAD~1")
    bad = check_scope_diff_paths(files, ctx.scope, ctx.deny)
    if bad:
        return GateResult(passed=False, gate="scope-diff", code="gate.scope_violation",
                          output_tail="\n".join(bad[-200:]), details={"files": bad, "scope": ctx.scope, "deny": ctx.deny})
    return GateResult(passed=True, gate="scope-diff", code="ok", output_tail="", details={"files": files})


def _depth(task_id: str, needs: dict[str, list[str]], seen: frozenset[str] = frozenset()) -> int:
    if task_id in seen:
        raise FactoryError("config.invalid", f"tasks need each other in a cycle at {task_id!r}", hint="remove the cycle from `needs`")
    return 1 + max((_depth(n, needs, seen | {task_id}) for n in needs.get(task_id, [])), default=0)


def delete_chained_branches(repo: Path, run_id: str, needs: dict[str, list[str]]) -> list[str]:
    """After the join, delete the task branches dependents first (module 7). A dependent was made from its
    dependency's branch, so the dependency's branch is deleted last. Returns the branches in the order deleted.
    This composes delete_branch and remove_worktree from the contract; it adds no new public contract."""
    order = sorted(needs, key=lambda t: _depth(t, needs), reverse=True)  # deepest dependent first
    deleted = []
    for task_id in order:
        branch = f"{run_id}--{task_id}"
        for wt in _worktrees_on(repo, branch):
            remove_worktree(wt, force=True)
        if _has_ref(repo, branch):
            delete_branch(repo, branch)
            deleted.append(branch)
    return deleted


def reset_dependents(repo: Path, cfg: Config, run_id: str, reworked: str, needs: dict[str, list[str]]) -> list[str]:
    """A task was reworked: every task that needs it, directly or not, is reset and recreated from its new branch
    (module 7). Returns the recreated task ids, dependencies first. Uses create_task_worktree, remove_worktree and
    delete_branch from the contract."""
    affected = {t for t in needs if reworked in _all_needs(t, needs)}
    recreated = []
    for task_id in sorted(affected, key=lambda t: _depth(t, needs)):
        branch = f"{run_id}--{task_id}"
        for wt in _worktrees_on(repo, branch):
            remove_worktree(wt, force=True)
        if _has_ref(repo, branch):
            delete_branch(repo, branch)
        bases = [f"{run_id}--{n}" for n in needs[task_id]] or [run_id]
        create_task_worktree(repo, cfg, run_id, task_id, base_branches=bases)
        recreated.append(task_id)
    return recreated


def _all_needs(task_id: str, needs: dict[str, list[str]], seen: frozenset[str] = frozenset()) -> set[str]:
    out: set[str] = set()
    for n in needs.get(task_id, []):
        if n in seen:
            raise FactoryError("config.invalid", f"tasks need each other in a cycle at {n!r}", hint="remove the cycle from `needs`")
        out |= {n} | _all_needs(n, needs, seen | {task_id})
    return out


def _worktrees_on(repo: Path, branch: str) -> list[Path]:
    out = git(repo, "worktree", "list", "--porcelain").stdout
    found, current = [], None
    for line in out.splitlines():
        if line.startswith("worktree "):
            current = Path(line.split(" ", 1)[1])
        elif line == f"branch refs/heads/{branch}" and current is not None:
            found.append(current)
    return found
