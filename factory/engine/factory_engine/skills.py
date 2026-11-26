"""Skills (module 10): resolve a stage's skill, install and verify the lock.

A stage resolves in a fixed order (module 10): a local override in .factory/config/overrides/, then the locked
upstream skill, then the factory's own fallback in factory/skills/own/. The factory ships its own skill for every
stage, so a repo with an empty skills.lock always resolves to an own skill.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .config import Config
from .errors import FactoryError
from .types import Problem
from .yamlio import load_yaml

KIT = Path(__file__).resolve().parents[2]  # the factory/ folder this engine ships in; set by use_kit()


def use_kit(path: Path) -> None:
    """Point the resolver at another kit folder (a repo's copy, or a run's snapshot)."""
    global KIT
    KIT = path


@dataclass
class SkillRef:
    name: str
    source: Literal["override", "locked", "own"]
    path: Path
    args: dict = field(default_factory=dict)


@dataclass
class LockReport:
    """G2: defined here. What install_locked did."""

    installed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # not on the allowlist, or denied
    problems: list[str] = field(default_factory=list)


def _stages_map(repo: Path) -> dict[str, dict]:
    base = load_yaml((KIT / "stages.map.yaml").read_text(), file="stages.map.yaml") or {}
    extra = repo / ".factory" / "config" / "overrides" / "stages.map.yaml"
    if extra.is_file():
        base = {**base, **(load_yaml(extra.read_text(), file=str(extra)) or {})}
    return base


def _lock(repo: Path) -> dict:
    for p in (repo / "factory" / "skills.lock", KIT / "skills.lock"):
        if p.is_file():
            return load_yaml(p.read_text(), file=str(p)) or {}
    return {}


def _cache() -> Path:
    from .loadcfg import factory_home
    return factory_home() / "skills-cache"


def resolve_skill(name: str, repo: Path, cfg: Config) -> SkillRef:
    """override -> locked upstream -> own fallback. FactoryError("skills.unknown") if none (module 10).

    A stage name maps to a skill through stages.map.yaml; a name that is already a skill name is used as it is."""
    mapping = _stages_map(repo).get(name, {})
    skill = (mapping.get("skill") or name)
    bare = skill.split(":", 1)[1] if ":" in skill else skill

    override = repo / ".factory" / "config" / "overrides" / "skills" / bare / "SKILL.md"
    if override.is_file():
        return SkillRef(name=bare, source="override", path=override.parent, args=mapping.get("args", {}))

    locked = _locked_path(repo, bare)
    if locked is not None:
        return SkillRef(name=bare, source="locked", path=locked, args=mapping.get("args", {}))

    own = KIT / "skills" / "own" / bare / "SKILL.md"
    if own.is_file():
        return SkillRef(name=bare, source="own", path=own.parent, args=mapping.get("args", {}))
    raise FactoryError("skills.unknown", f"no skill {bare!r} for {name!r}: no override, no locked skill, no own skill",
                       hint="add the skill to factory/skills/own/, or an override in .factory/config/overrides/skills/")


def lock_allow(repo: Path) -> dict[str, list[str]]:
    """The allowlist in skills.lock, by source. A plugin's `requires.skills` must name skills in it (module 5)."""
    return dict(_lock(repo).get("allow") or {})


def _locked_path(repo: Path, skill: str) -> Path | None:
    lock = _lock(repo)
    for source, names in (lock.get("allow") or {}).items():
        if skill not in (names or []) or skill in ((lock.get("deny") or {}).get(source) or []):
            continue
        candidate = _cache() / source / skill
        if (candidate / "SKILL.md").is_file():
            return candidate
    return None


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def install_locked(repo: Path, cfg: Config) -> LockReport:
    """Fetch each pinned ref and install only the allowed, not denied, skills (module 10)."""
    lock, report = _lock(repo), LockReport()
    for source, spec in (lock.get("sources") or {}).items():
        allowed = set((lock.get("allow") or {}).get(source) or [])
        denied = set((lock.get("deny") or {}).get(source) or [])
        if not allowed:
            report.skipped.append(f"{source}: nothing on the allowlist, so nothing is fetched")
            continue
        dest = _cache() / "_clones" / source
        if not dest.exists():
            r = _git("clone", "--quiet", str(spec["repo"]), str(dest))
            if r.returncode != 0:
                report.problems.append(f"{source}: clone failed: {r.stderr.strip()[:200]}")
                continue
        _git("fetch", "--quiet", "origin", cwd=dest)
        r = _git("checkout", "--quiet", str(spec["ref"]), cwd=dest)
        if r.returncode != 0:
            report.problems.append(f"{source}: ref {spec['ref']} not found")
            continue
        for skill in sorted(allowed - denied):
            src = dest / skill
            if not (src / "SKILL.md").is_file():
                report.problems.append(f"{source}/{skill}: not found at {spec['ref']}")
                continue
            target = _cache() / source / skill
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
            report.installed.append(f"{source}/{skill}")
        report.skipped.extend(f"{source}/{s}" for s in sorted(denied))
    return report


def tree_hash(path: Path) -> str:
    d = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file()):
        d.update(str(f.relative_to(path)).encode() + b"\0" + f.read_bytes() + b"\0")
    return d.hexdigest()[:12]


def verify_lock(repo: Path) -> list[Problem]:
    """Refs present and hashes match (module 10). A changed upstream ref is reported."""
    lock, problems = _lock(repo), []
    for source, spec in (lock.get("sources") or {}).items():
        dest = _cache() / "_clones" / source
        if not dest.exists():
            problems.append(Problem("skills.lock", None, f"{source}: not installed", "run factory upgrade to install the pinned skills"))
            continue
        head = _git("rev-parse", "HEAD", cwd=dest).stdout.strip()
        want = _git("rev-parse", f"{spec['ref']}^{{commit}}", cwd=dest).stdout.strip()
        if not want:
            problems.append(Problem("skills.lock", None, f"{source}: pinned ref {spec['ref']} is not in the clone",
                                    "check the ref, then reinstall"))
        elif head != want:
            problems.append(Problem("skills.lock", None, f"{source}: installed {head[:8]} but the lock pins {want[:8]}",
                                    "run factory upgrade to install the pinned ref"))
    return problems


PRACTICE_MAX_LINES_DEFAULT = 150
_REVIEW_STAGES = ("review-standards", "review-spec", "critique")


def practice_packs(languages: list[str], stage: str, repo: Path, cfg: Config) -> list[SkillRef]:
    """The practice packs a task gets (module 10, phase 1b mechanism): one per language the task touches, chosen by
    the caller from 17A's detect and the task's scope, so a Java-only task never gets the TypeScript pack.

    A team override in .factory/config/overrides/practices/<lang>/ replaces the shipped pack, or is merged over it when
    its SKILL.md says `merge: true` in its front matter. Review stages get `review.md`; other stages get the core rules.
    Returns pointers (a path each), never the pack's text."""
    packs: list[SkillRef] = []
    for lang in dict.fromkeys(languages):  # keep order, drop duplicates
        shipped = KIT / "skills" / "own" / "practices" / lang
        override = repo / ".factory" / "config" / "overrides" / "practices" / lang
        chosen = None
        if (override / "SKILL.md").is_file():
            merge = _front_matter(override / "SKILL.md").get("merge") is True
            chosen = ("override", override, {"merged_over": str(shipped)} if merge and (shipped / "SKILL.md").is_file() else {})
        elif (shipped / "SKILL.md").is_file():
            chosen = ("own", shipped, {})
        if chosen is None:
            continue
        source, path, args = chosen
        args = {**args, "stage_file": "review.md" if stage in _REVIEW_STAGES and (path / "review.md").is_file() else "SKILL.md"}
        packs.append(SkillRef(name=f"practices-{lang}", source=source, path=path, args=args))  # type: ignore[arg-type]
    return packs


def _front_matter(skill_md: Path) -> dict:
    text = skill_md.read_text()
    if not text.startswith("---"):
        return {}
    return load_yaml(text.split("---", 2)[1]) or {}


def oversized_packs(repo: Path, cfg: Config) -> list[Problem]:
    """Packs over `practices.max_lines` (default 150), for `factory doctor` (module 10)."""
    limit = int(((cfg.repo or {}).get("practices") or {}).get("max_lines", PRACTICE_MAX_LINES_DEFAULT))
    problems = []
    for root in (KIT / "skills" / "own" / "practices", repo / ".factory" / "config" / "overrides" / "practices"):
        for md in sorted(root.glob("*/SKILL.md")) if root.is_dir() else []:
            n = len(md.read_text().splitlines())
            if n > limit:
                problems.append(Problem(str(md), None, f"{md.parent.name} is {n} lines; the limit is {limit}",
                                        "move detail into a topic file the pack points to"))
    return problems
