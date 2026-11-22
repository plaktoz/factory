"""Kit and repo setup (module 3): init_repo, upgrade, doctor.

The kit is `factory/`, replaced whole on upgrade and never edited. Local settings live in `.factory/config/` and are
committed; `.factory/` itself is ignored except `config/` (module 3), so the repo's own .gitignore is never edited.
Where the kit comes from (the installed CLI's bundled copy) is module 16's packaging question. The functions keep
the spec's signatures, so the source is the module setting `KIT_SOURCE` (this engine's own `factory/` folder), which a
test or the launcher sets with `use_kit_source()`.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .errors import FactoryError
from .types import CheckResult
from .validate import validate
from .yamlio import load_yaml

KIT_SOURCE = Path(__file__).resolve().parents[2]  # the `factory/` folder this engine ships in


def use_kit_source(path: Path) -> None:
    """Set where init_repo and upgrade copy the kit from."""
    global KIT_SOURCE
    KIT_SOURCE = path
INNER_GITIGNORE = "*\n!config/\n!config/**\n!.gitignore\n"  # !config/** is needed; see module 3

STARTER_FACTORY_YAML = """base_branch: main
tracker: github
harness: claude
"""
STARTER_MERGE_POLICY = """default: human
auto:
  workflows: []
  type_source: [explicit, label, front_matter]
  require:
    gates: all_passed
    ci: green
    max_files: 10
    max_lines: 300
never_auto_if:
  paths: ["**/migrations/**", "auth/**", "infra/**", ".github/**", "factory/**", ".factory/config/**"]
  dependency_manifests_changed: true
  architecture_decision: true
  review_findings_at_or_above: medium
  notes_used: true
  rework_loops_used_at_least: 2
"""


@dataclass
class InitReport:
    """Defined here: the spec names it without fields (gap G2). Only what init_repo can truthfully report."""

    created: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)


@dataclass
class UpgradeReport:
    replaced: Path | None = None
    config_untouched: bool = True
    problems: list[str] = field(default_factory=list)


def _write_if_absent(path: Path, text: str, report: InitReport) -> None:
    if path.exists():
        report.unchanged.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    report.created.append(path)


def _copy_kit(src: Path, dst: Path) -> None:
    """Copy the kit to `dst`. A kit already there is replaced only after the whole copy succeeds: the new one is built
    in a scratch folder beside it, the old one is moved aside, and the scratch folder takes its place. A failure at any
    point leaves the old kit whole and no scratch folder behind."""
    if not src.is_dir():
        raise FactoryError("config.invalid", f"kit source {src} is not a folder", hint="pass the folder that holds the kit")
    if dst.exists() and src.resolve() == dst.resolve():
        raise FactoryError("config.invalid", f"{dst} is both the kit source and the folder to replace",
                           hint="run upgrade from a kit that lives outside this repo's factory/ folder")
    scratch, aside = dst.with_name(dst.name + ".new"), dst.with_name(dst.name + ".old")
    for leftover in (scratch, aside):  # left by a process that died between the steps below
        shutil.rmtree(leftover, ignore_errors=True)
    try:
        shutil.copytree(src, scratch, ignore=_ignore_engine_tests(src))
        if dst.exists():
            os.replace(dst, aside)
        os.replace(scratch, dst)
    except OSError as e:
        shutil.rmtree(scratch, ignore_errors=True)
        if aside.exists() and not dst.exists():
            os.replace(aside, dst)
        raise FactoryError("config.invalid", f"could not copy the kit to {dst}: {e}",
                           hint=f"{dst} is unchanged; free the space or fix the permissions, then run upgrade again") from e
    shutil.rmtree(aside, ignore_errors=True)


def _ignore_engine_tests(src: Path):
    """copytree ignore hook: the usual junk, plus factory/engine/tests (not the engine itself, which each snapshot needs)."""
    skip = shutil.ignore_patterns(".venv", "__pycache__", "*.pyc", ".pytest_cache", ".gitkeep")

    def ignore(folder: str, names: list[str]) -> set[str]:
        out = set(skip(folder, names))
        if Path(folder) == src / "engine" and "tests" in names:
            out.add("tests")
        return out

    return ignore


def init_repo(repo: Path) -> InitReport:
    """Create the layout. A second run changes nothing, and the repo's root .gitignore is never edited."""
    if not repo.is_dir():
        raise FactoryError("config.invalid", f"{repo} is not a folder", hint="run init from a repo's folder")
    report = InitReport()
    kit = repo / "factory"
    if kit.exists():
        report.unchanged.append(kit)
    else:
        _copy_kit(KIT_SOURCE, kit)
        report.created.append(kit)
    _write_if_absent(repo / ".factory" / ".gitignore", INNER_GITIGNORE, report)
    _write_if_absent(repo / ".factory" / "config" / "factory.yaml", STARTER_FACTORY_YAML, report)
    _write_if_absent(repo / ".factory" / "config" / "merge-policy.yaml", STARTER_MERGE_POLICY, report)
    for d in ("workflows", "plugins", "overrides"):
        (repo / ".factory" / "config" / d).mkdir(parents=True, exist_ok=True)
    (repo / ".factory" / "inbox").mkdir(parents=True, exist_ok=True)
    return report


def upgrade(repo: Path, version: str) -> UpgradeReport:
    """Replace factory/ whole and validate .factory/config/ against the new schemas. Never touches .factory/config/.

    `version` names the kit being installed; it is recorded in the report only, because choosing a kit by version is
    the launcher's job (module 16). A run created earlier keeps its own snapshot, so nothing here affects it."""
    if not (repo / "factory").is_dir():
        raise FactoryError("config.invalid", f"{repo} has no factory/ folder", hint="run factory init first")
    before = {p: p.read_bytes() for p in (repo / ".factory" / "config").rglob("*") if p.is_file()}
    report = UpgradeReport()
    _copy_kit(KIT_SOURCE, repo / "factory")
    report.replaced = repo / "factory"
    for name, schema in (("factory.yaml", "factory-config"), ("merge-policy.yaml", "merge-policy")):
        path = repo / ".factory" / "config" / name
        if path.is_file():
            try:
                validate(load_yaml(path.read_text(), file=str(path)), schema, file=str(path))
            except FactoryError as e:
                report.problems.append(e.message)
    after = {p: p.read_bytes() for p in (repo / ".factory" / "config").rglob("*") if p.is_file()}
    report.config_untouched = before == after
    return report


def _which(cmd: str, env: Mapping[str, str]) -> str | None:
    return shutil.which(cmd, path=env.get("PATH", ""))


def doctor(repo: Path | None, *, as_scheduler: bool = False) -> list[CheckResult]:
    """Check the tools and settings a run needs. With as_scheduler, run in an empty, cron-like environment.

    Only what module 3 owns: git, gh, credentials and the repo's settings. It imports no other module, because 9, 10
    and 17A depend on 3. The driver (module 16, `api.doctor`) adds their checks to this list."""
    base = dict(os.environ)
    if as_scheduler:
        # what cron gives a job: a short PATH, no profile, no secrets
        base = {"PATH": "/usr/bin:/bin", "HOME": base.get("HOME", "")}
    out: list[CheckResult] = []
    for tool, hint in (("git", "install git"), ("gh", "install the GitHub CLI when the tracker is github")):
        found = _which(tool, base)
        out.append(CheckResult(tool, found is not None, found or f"{tool} is not on PATH", "" if found else hint))
    creds = [k for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN") if base.get(k)]
    ok = bool(creds) and (base.get("ANTHROPIC_API_KEY") or base.get("ANTHROPIC_BASE_URL"))
    out.append(CheckResult("credentials", bool(ok),
                           "key or gateway token found" if ok else "no ANTHROPIC_API_KEY, or no ANTHROPIC_AUTH_TOKEN with ANTHROPIC_BASE_URL",
                           "" if ok else "set ANTHROPIC_API_KEY, or ANTHROPIC_AUTH_TOKEN with ANTHROPIC_BASE_URL; a login session is not supported in phase 1"))
    if repo is not None:
        cfg = repo / ".factory" / "config" / "factory.yaml"
        if not cfg.is_file():
            out.append(CheckResult("repo-config", False, f"{cfg} is missing", "run factory init"))
        else:
            try:
                validate(load_yaml(cfg.read_text(), file=str(cfg)), "factory-config", file=str(cfg))
                out.append(CheckResult("repo-config", True, "factory.yaml is valid", ""))
            except FactoryError as e:
                out.append(CheckResult("repo-config", False, e.message, e.hint))
    return out
