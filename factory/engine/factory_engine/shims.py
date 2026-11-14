"""Skill shims (module 10): `.claude/skills/factory-<skill>` links inside each worktree.

Two patterns in the repo's shared `.git/info/exclude` hide them, so they never show in `git status` and are never
committed (module 7). Claude only in phase 1; Codex's `.agents/skills` is phase 2."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .errors import FactoryError
from .skills import SkillRef

CLAUDE_DIR = Path(".claude") / "skills"
EXCLUDE_PATTERNS = (".claude/skills/factory-*", ".agents/skills/factory-*")  # the second is for phase 2


def _exclude_file(worktree: Path) -> Path:
    r = subprocess.run(["git", "-C", str(worktree), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise FactoryError("git.command_failed", f"{worktree} is not a git worktree: {r.stderr.strip()[:200]}",
                           hint="generate shims inside a worktree the engine created")
    return Path(r.stdout.strip()) / "info" / "exclude"


def ensure_excludes(worktree: Path) -> None:
    """Write the two exclude patterns once per repo. The file is shared by every worktree of the repo."""
    path = _exclude_file(worktree)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text().splitlines() if path.exists() else []
    missing = [p for p in EXCLUDE_PATTERNS if p not in existing]
    if missing:
        path.write_text("\n".join(existing + missing) + "\n")


def generate_shims(worktree: Path, harnesses: list[str], skills: list[SkillRef]) -> list[Path]:
    """Link each skill into the worktree as `factory-<skill>` and make sure the exclude patterns exist.

    Phase 1 accepts only `claude`; any other harness fails fast. Returns the links made. Running it twice changes
    nothing: an existing correct link is kept."""
    for h in harnesses:
        if h != "claude":
            raise FactoryError("config.invalid", f"harness {h!r}: phase 1 accepts only claude",
                               hint="set harness: claude; Codex is not supported yet")
    ensure_excludes(worktree)
    base = worktree / CLAUDE_DIR
    base.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for skill in skills:
        link = base / f"factory-{skill.name}"
        target = skill.path.resolve()
        if link.is_symlink() and Path(os.readlink(link)).resolve() == target:
            made.append(link)
            continue
        if link.exists() or link.is_symlink():
            link.unlink() if link.is_symlink() else _remove_tree(link)
        link.symlink_to(target, target_is_directory=True)
        made.append(link)
    return made


def _remove_tree(path: Path) -> None:
    import shutil
    shutil.rmtree(path)
