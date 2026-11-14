"""worktree_path (module 3): the template is rendered and the result must be outside the repo (except the
factory's own .factory/worktrees) and must not already exist."""

from __future__ import annotations

from pathlib import Path

from .errors import FactoryError


def render(template: str, *, root: Path, repo: str, owner: str, run_id: str, task: str | None) -> Path:
    values = {"root": str(root), "repo": repo, "owner": owner, "run_id": run_id, "task": task or ""}
    try:
        out = template.format(**values)
    except KeyError as e:
        raise FactoryError("config.invalid", f"worktree_path: unknown placeholder {e}",
                           hint="use {root}, {repo}, {owner}, {run_id} or {task}") from e
    if task is not None:
        out = out + (f"--{task}" if "{task}" not in template else "")
    return Path(out)


def check_outside_repo(path: Path, repo: Path) -> None:
    p = path.resolve()
    r = repo.resolve()
    if p == r or r in p.parents:
        if r / ".factory" / "worktrees" in p.parents or p.parent == r / ".factory" / "worktrees":
            return
        raise FactoryError("config.invalid", f"worktree {p} is inside the repo {r}",
                           hint="set worktree_root outside the repo (default: ~/.factory/worktrees)")


def check_not_existing(path: Path) -> None:
    if path.exists():
        raise FactoryError("config.invalid", f"worktree path {path} already exists",
                           hint="remove it or use a new run id")
