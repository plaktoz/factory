"""Skill shims (module 10): `factory-<skill>` links inside each worktree, under `.claude/skills` for Claude and
`.agents/skills` for Codex.

Two patterns in the repo's shared `.git/info/exclude` hide them, so they never show in `git status` and are never
committed (module 7)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .errors import FactoryError
from .skills import SkillRef

SKILL_DIRS = {"claude": Path(".claude") / "skills", "codex": Path(".agents") / "skills"}
EXCLUDE_PATTERNS = (".claude/skills/factory-*", ".agents/skills/factory-*")


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

    Each harness gets its own skills directory (`SKILL_DIRS`); any other harness fails fast. Returns the links
    made. Running it twice changes nothing: an existing correct link is kept."""
    for h in harnesses:
        if h not in SKILL_DIRS:
            raise FactoryError("config.invalid", f"harness {h!r}: the accepted harnesses are claude and codex",
                               hint="set harness: claude or harness: codex")
    ensure_excludes(worktree)
    made: list[Path] = []
    for h in harnesses:
        base = worktree / SKILL_DIRS[h]
        base.mkdir(parents=True, exist_ok=True)
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
