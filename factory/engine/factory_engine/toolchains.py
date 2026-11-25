"""Language toolchains (module 17A): detect profiles, run their steps, gate lint, build verify tasks.

A profile is a YAML file in factory/languages/ (or a repo override). Commands are argument lists, run with no shell,
in the worktree. The formatter and lint steps run with a plain subprocess, not under `srt`: the spec does not say they
are sandboxed (open, see docs/tasks.md). The cache variables a tool needs are set by the adapter (module 9), not by the profile.
"""

from __future__ import annotations

import shutil

import fnmatch
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .adapters.worker.sandbox import plain_hosts
from .config import Config
from .errors import FactoryError
from .types import GateContext, GateResult, GateSpec, TaskSpec
from .yamlio import load_yaml

KIT = Path(__file__).resolve().parents[2]
STEPS = ("format", "format_check", "lint", "test", "build")


@dataclass
class Toolchain:
    """G2: one detected profile with its chosen variant."""

    name: str
    variant: str
    files: list[str]
    commands: dict[str, list[str]]
    root: Path
    cache_env: dict[str, str] = field(default_factory=dict)
    # The programs doctor checks, when a step is a wrapper whose argv[0] is an interpreter (a JUnit test step).
    tools: list[str] = field(default_factory=list)
    # Per step, the registry hosts the step may reach under srt (module 17A `network`). A step not listed has none.
    network: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class StepResult:
    """G2: what run_step did."""

    step: str
    exit_code: int | None
    ok: bool
    missing_tool: str | None
    output_tail: str
    files: list[str] = field(default_factory=list)


@dataclass
class Finding:
    """G2: one lint finding, as the feedback record lists it (module 17A)."""

    file: str
    line: int | None
    rule: str
    message: str


def _profiles(repo: Path) -> list[dict]:
    out: list[dict] = []
    for d in (KIT / "languages", repo / ".factory" / "config" / "languages"):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.yaml")):
            doc = load_yaml(p.read_text(), file=str(p)) or {}
            name = doc.get("name")
            if name:
                out = [x for x in out if x.get("name") != name] + [doc]  # a repo profile replaces the shipped one
    return out


def _exists_any(worktree: Path, names: list[str]) -> bool:
    for n in names:
        if "*" in n or "?" in n:
            if any(fnmatch.fnmatch(p.name, n) for p in worktree.iterdir() if p.is_file()):
                return True
        elif (worktree / n).is_file():
            return True
    return False


def _variant(profile: dict, worktree: Path) -> str | None:
    for vname, v in (profile.get("variants") or {}).items():
        when = v.get("when") or {}
        if "file" in when and (worktree / when["file"]).is_file():
            return vname
        if "any_file" in when and _exists_any(worktree, when["any_file"]):
            return vname
    return None


def _network(v: dict, where: str) -> dict[str, list[str]]:
    """The `network` key of one variant: each step named in STEPS maps to a list of plain hostnames (module 17A). A step
    name it does not know, or a host that is not a plain hostname, is refused at load, so no profile can widen the
    sandbox by a typo or a wildcard."""
    out: dict[str, list[str]] = {}
    for step, hosts in (v.get("network") or {}).items():
        if step not in STEPS:
            raise FactoryError("config.invalid", f"{where}: network names step {step!r}, which is not one of {', '.join(STEPS)}",
                               hint="key network by a step name: format, format_check, lint, test or build")
        out[step] = plain_hosts(hosts, f"{where}.network.{step}")
    return out


def detect(worktree: Path, cfg: Config) -> list[Toolchain]:
    """Profiles that apply to this worktree, with their variant chosen (module 17A). A profile with no variant is
    not detected; a repo with two variants of one profile picks the first in the order the profile lists them."""
    found: list[Toolchain] = []
    for p in _profiles(worktree):
        det = p.get("detect") or {}
        if not _exists_any(worktree, list(det.get("any_file") or [])):
            continue
        variant = _variant(p, worktree)
        if variant is None:
            continue
        v = p["variants"][variant]
        where = f"languages/{p['name']}.yaml variant {variant}"
        found.append(Toolchain(name=p["name"], variant=variant, files=list(p.get("files") or []),
                               commands={s: list(v[s]) for s in STEPS if v.get(s) is not None}, root=worktree,
                               tools=list(v.get("tools") or []), network=_network(v, where)))
    return found


def find_tool(worktree: Path, name: str) -> str | None:
    """The program a profile command starts. `gradlew` is the repo's own wrapper script, not a tool on PATH (module 17A:
    `gradlew` or `gradlew.bat`, chosen per OS), so it is looked for in the worktree first."""
    from shutil import which
    if name == "gradlew":
        for wrapper in ("gradlew", "gradlew.bat"):
            if (worktree / wrapper).is_file():
                return str(worktree / wrapper)
    return which(name)


def run_step(tc: Toolchain, step: Literal["format", "format_check", "lint", "test", "build"],
             worktree: Path, *, files: list[str] | None = None, log: Path) -> StepResult:
    """Run one step of a toolchain in the worktree. A missing tool fails fast with its name (module 17A).
    A formatter that exits non-zero is a task error, reported by its exit code; lint findings are the caller's rework."""
    if step not in STEPS:
        raise FactoryError("config.invalid", f"unknown step {step!r}", hint=f"use one of {', '.join(STEPS)}")
    cmd = list(tc.commands.get(step) or [])
    if not cmd:
        return StepResult(step, 0, True, None, "", files or [])  # e.g. python build: nothing to run
    tool = find_tool(worktree, cmd[0])
    if tool is None:
        raise FactoryError("config.invalid", f"{tc.name}: the tool {cmd[0]!r} for {step} is not installed",
                           hint=f"install {cmd[0]} before the run; factory doctor reports this too")
    cmd[0] = tool
    args = cmd + ([f for f in (files or [])] if step in ("format", "lint") and files else [])
    # Under srt, like every cmd task and gate command (module 9; owner answer 2026-11-22). The environment is the minimal
    # base; the cache variables for this task are set by the adapter (module 9), not by this step's signature.
    wrapped, folder = _sandboxed(worktree, args, tc.network.get(step, []))
    try:
        r = subprocess.run(wrapped, cwd=worktree, capture_output=True, text=True, env=_base_env())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(r.stdout + r.stderr)
    tail = "\n".join((r.stdout + r.stderr).splitlines()[-200:])
    return StepResult(step, r.returncode, r.returncode == 0, None, tail, files or [])


# Formatters that format a whole project and read a file name as something else (a Maven phase, a solution path).
_WHOLE_PROJECT_FORMATTERS = frozenset({"mvn", "gradlew", "dotnet"})


def format_changed_files(worktree: Path, cfg: Config, changed: list[str], *, log_dir: Path) -> list[StepResult]:
    """Format a task's changed files once, after its worker has stopped (module 17A, step 1). Each detected profile
    formats the changed files its `files` globs match; a profile with none does not run. A build-tool formatter runs
    once with no file arguments. A formatter that exits non-zero is returned, not raised; a missing tool raises
    `config.invalid` with its name (run_step)."""
    present = [f for f in changed if (worktree / f).is_file()]
    results: list[StepResult] = []
    for tc in detect(worktree, cfg):
        mine = [f for f in present if _matches(f, tc.files)]
        if not mine or "format" not in tc.commands:
            continue
        whole = tc.commands["format"][0] in _WHOLE_PROJECT_FORMATTERS
        results.append(run_step(tc, "format", worktree, files=None if whole else mine, log=log_dir / f"format-{tc.name}.log"))
    return results


def _matches(path: str, globs: list[str]) -> bool:
    """`**/*.py` matches `a.py` as well as `sub/a.py`: fnmatch's `*` crosses `/`, but a `**/` prefix needs a folder."""
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(path, g.removeprefix("**/")) for g in globs)


def _sandboxed(worktree: Path, args: list[str], domains: list[str] | None = None) -> tuple[list[str], Path]:
    """The srt command for one step, and the folder its settings file is in. The worktree is writable and the factory
    home is denied, as for a worker; `domains` is this step's own allowance (module 17A `network`, empty by default).
    The caller removes the folder when the step is done."""
    import json
    import tempfile
    from .adapters.worker import sandbox
    from .loadcfg import factory_home
    home_tmp = factory_home() / "tmp"
    home_tmp.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="fmt-", dir=home_tmp))
    settings = folder / "srt-settings.json"
    settings.write_text(json.dumps(sandbox.srt_settings(worktree, folder, domains=list(domains or []))))
    return sandbox.srt_command(sandbox.require_srt(), settings, args), folder


def _base_env() -> dict[str, str]:
    import os
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
    return {k: os.environ[k] for k in keep if k in os.environ}


_RUFF = re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+):\d+:\s*(?P<rule>[A-Z]+\d+)\s+(?P<msg>.*)$")
_GENERIC = re.compile(r"^(?P<file>[^:\s]+\.[A-Za-z]+):(?P<line>\d+)(?::\d+)?:\s*(?P<msg>.*)$")


def parse_findings(tc: Toolchain, output: str) -> list[Finding]:
    """file, line, rule and message from a lint tool's output (module 17A). Recognises the ruff form
    `file:line:col: RULE message`; other tools use the generic `file:line: message` form with rule `lint`."""
    out: list[Finding] = []
    for line in output.splitlines():
        m = _RUFF.match(line)
        if m:
            out.append(Finding(m["file"], int(m["line"]), m["rule"], m["msg"]))
            continue
        g = _GENERIC.match(line)
        if g:
            out.append(Finding(g["file"], int(g["line"]), "lint", g["msg"].strip()))
    return out


def check_lint_clean(spec: GateSpec, ctx: GateContext) -> GateResult:
    """The lint-clean gate (module 17A, used by 8): run format_check and lint on changed files. A violation fails the
    gate and its feedback lists each finding's file, line and rule."""
    findings: list[Finding] = []
    failed_steps: list[str] = []
    for tc in detect(ctx.worktree, ctx.cfg):
        for step in ("format_check", "lint"):
            if step not in tc.commands:
                continue
            res = run_step(tc, step, ctx.worktree, log=ctx.worktree.parent / f"lint-{tc.name}-{step}.log")
            if not res.ok:
                failed_steps.append(f"{tc.name}:{step}")
                findings.extend(parse_findings(tc, res.output_tail))
    if failed_steps:
        return GateResult(passed=False, gate="lint-clean", code="gate.lint",
                          output_tail="\n".join(f"{f.file}:{f.line}: {f.rule} {f.message}" for f in findings[-200:]),
                          details={"steps": failed_steps, "findings": [f.__dict__ for f in findings]})
    return GateResult(passed=True, gate="lint-clean", code="ok", output_tail="", details={})


def language_tasks(worktree: Path, cfg: Config, step: str, changed: list[str]) -> list[TaskSpec]:
    """One task per detected language whose files the run changed, for tasks_from: languages (module 17A, verify stage;
    owner decision D5, 2026-11-22). `changed` is the run's changed paths, relative to the worktree. Tasks run in
    parallel: none depends on another. A test task names `test.junit.xml`, the file its step writes into the task
    folder, so the engine waits for it."""
    from .types import HelperPolicy
    tasks = []
    for tc in detect(worktree, cfg):
        if step not in tc.commands or not any(_matches(f, tc.files) for f in changed):
            continue
        out = "test.junit.xml" if step == "test" else None
        tasks.append(TaskSpec(id=f"{step}-{tc.name}", skill=None, cmd=tc.commands[step], run=None, scope=[],
                              deny=[], needs=[], helpers=HelperPolicy("off", 0, [], None), out=out,
                              timeout_minutes=30, retries=0, model=None, when=None,
                              network_domains=list(tc.network.get(step, []))))
    return tasks


def uncovered_files(worktree: Path, cfg: Config, step: str, changed: list[str]) -> list[str]:
    """The changed paths that no language task for `step` covers. A path is covered when a detected profile with that
    step owns it by its source globs, or it is the profile's own build file (pom.xml, package.json), which belongs to
    the language it configures. A run reports the rest, so a file nothing tested is named, not skipped silently."""
    tcs = [tc for tc in detect(worktree, cfg) if step in tc.commands]
    names = {tc.name for tc in tcs}
    globs = sorted({g for tc in tcs for g in tc.files})
    builds = [b for p in _profiles(worktree) if p["name"] in names
              for b in ((p.get("detect") or {}).get("any_file") or [])]
    return sorted(f for f in changed if not _matches(f, globs) and not _matches(f, builds))


def doctor_checks(worktree: Path, cfg: Config) -> list:
    """`factory doctor` checks for the toolchains a repo uses (module 17A): every tool each detected profile names
    must be installed. A missing tool is reported with its install hint, before any run starts."""
    from .types import CheckResult
    from shutil import which
    out = []
    for tc in detect(worktree, cfg):
        tools = sorted({cmd[0] for cmd in tc.commands.values() if cmd} | set(tc.tools))
        for tool in tools:
            ok = find_tool(worktree, tool) is not None
            out.append(CheckResult(f"toolchain:{tc.name}:{tool}", ok, "installed" if ok else f"{tool} is not on PATH",
                                   "" if ok else f"install {tool}; the {tc.name} profile needs it"))
    return out
