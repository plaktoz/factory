"""The repo engine's driver functions (module 16): one function per command, each composing modules.

Only drivers compose modules and only drivers may import `engine.py`. The blocked-run actions of module 8 (retry,
goto, skip) change a run and start no worker, so they build an Engine with no worker adapter. `spawn_engine` is the
one function that starts work. Every other function that needs a worker, tracker or pull request takes the real
adapter from the `default_*` functions here, or one the caller passes to `engine_for`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from . import decisions, housekeeping, intake, kit, state
from . import notes as notes_store
from . import usage as usage_mod
from .adapters.tracker.base import TrackerAdapter
from .adapters.worker.base import WorkerAdapter
from .adapters.worker.claude import ClaudeAdapter
from .clock import SystemClock
from .config import Config
from .decisions import Outcome
from .engine import Engine, EngineResult
from .errors import FactoryError
from .gh import FileTracker, GitHubPullRequests, GitHubTracker
from .housekeeping import GcPlan
from .intake import SyncReport
from .loadcfg import load_config
from .notes import NoteRef
from .prs import PullRequests
from .types import CheckResult, RunRef, Source
from .usage import UsageReport


def _gh_runner(repo: Path) -> Callable[[list[str]], subprocess.CompletedProcess]:
    """gh finds the GitHub repo from its working folder, so every call runs in the repo the driver was given."""
    def run(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(["gh", *args], capture_output=True, text=True, cwd=repo)
    return run


def default_workers(cfg: Config) -> dict[str, WorkerAdapter]:
    """The configured harness, with its real adapter. Phase 1a has only the Claude harness in the schema."""
    harness = (cfg.repo or {}).get("harness", "claude")
    if harness != "claude":
        raise FactoryError("config.invalid", f"harness {harness!r} has no adapter in this build",
                           hint="set harness: claude in .factory/config/factory.yaml")
    return {harness: ClaudeAdapter()}


class _InboxStatusOnly:
    """A file tracker that writes status and reads nothing. intake reads the inbox's markdown files itself, so a
    tracker that also listed them would create every run twice."""

    def __init__(self, inbox: FileTracker):
        self._inbox = inbox

    def list_new(self, since: str | None) -> list[Source]:
        return []

    def fetch(self, ref: str) -> Source:
        return self._inbox.fetch(ref)

    def set_status(self, ref: str, status: str, *, comment: str | None = None, link: str | None = None) -> None:
        self._inbox.set_status(ref, status, comment=comment, link=link)

    def ensure_labels(self, labels: list[str]) -> None:
        self._inbox.ensure_labels(labels)


def default_tracker(repo: Path, cfg: Config) -> TrackerAdapter:
    if ((cfg.repo or {}).get("tracker") or "github") == "file":
        return _InboxStatusOnly(FileTracker(repo / ".factory" / "inbox"))
    return GitHubTracker(runner=_gh_runner(repo))


def default_prs(repo: Path, cfg: Config) -> PullRequests:
    return GitHubPullRequests(runner=_gh_runner(repo))


def engine_for(repo: Path, cfg: Config, *, workers: Mapping[str, WorkerAdapter], tracker, prs,
               command: WorkerAdapter | None = None, owner: str = "cli") -> Engine:
    """An engine on these adapters. The CLI and the tests pass their own; the api defaults are the real ones.
    `command` runs the `cmd`, script and python tasks; left out, it is the real CommandAdapter under srt."""
    return Engine(repo, cfg, workers=dict(workers), tracker=tracker, prs=prs, command=command, owner=owner)


def _ref(repo: Path, run_id: str) -> RunRef:
    ref = state.find_run(state.factory_home(), run_id)
    if ref is None:
        raise FactoryError("config.invalid", f"no run named {run_id!r}", hint="factory status lists the runs in this repo")
    return ref


def _engine(repo: Path) -> Engine:
    return Engine(repo, load_config(repo), workers={}, tracker=None, prs=None, owner="cli")


# ---- intake and runs ---------------------------------------------------------------------------------------------

def add(repo, title, *, type=None, body=None, files=None) -> RunRef:
    """Create a run from CLI text or files. Starts no engine; the CLI decides that (`--no-run`)."""
    return intake.add(Path(repo), load_config(Path(repo)), title, type=type, body=body, files=files)


def sync(repo) -> SyncReport:
    """Read each source once and create runs for new requests. Starts no engine."""
    repo = Path(repo)
    cfg = load_config(repo)
    return intake.sync(repo, cfg, default_tracker(repo, cfg))


def run(repo, run_ids=None) -> EngineResult:
    """Drive the runs (or every run of this repo) until each is done, failed, aborted, blocked or waiting."""
    repo = Path(repo)
    cfg = load_config(repo)
    eng = engine_for(repo, cfg, workers=default_workers(cfg), tracker=default_tracker(repo, cfg),
                     prs=default_prs(repo, cfg))
    return eng.run(run_ids)


def decide(repo, run_id, stage, *, packet_sha, choices=None, questions=None,
           notes="", by, channel) -> Outcome:
    """Record an answer to a human stop. Refuses a stale packet or a bad choice, and changes nothing then."""
    ref = _ref(Path(repo), run_id)
    visit = decisions.latest_visit(state.read_run(ref.run_dir), stage)
    return decisions.record(ref.run_dir, stage, visit, packet_sha=packet_sha, choices=choices, questions=questions,
                           notes=notes, by=by, channel=channel)


def note(repo, run_id, task_id, text, *, deny=None) -> NoteRef:
    """Queue a note that the task's next attempt receives."""
    ref = _ref(Path(repo), run_id)
    return notes_store.queue_note(ref.run_dir, task_id, text, deny=deny, by="cli")


# ---- blocked-run actions (module 8, driven by module 16) -------------------------------------------------------

def retry(repo, run_id, *, stage=None, note=None) -> None:
    """Run a blocked stage once more, with the note queued as feedback. Loop counters are unchanged."""
    _engine(Path(repo)).retry(run_id, stage=stage, note=note)


def goto(repo, run_id, stage) -> None:
    """Send a blocked run back to this stage or an earlier one. The stage and every later stage start again."""
    _engine(Path(repo)).goto(run_id, stage)


def skip(repo, run_id, gate, *, reason) -> None:
    """Pass a gate the workflow marks `skippable: true`. Logs the skip and stops auto-merge."""
    _engine(Path(repo)).skip(run_id, gate, reason=reason)


def abort(repo, run_id, *, reason) -> None:
    """End a run as aborted and close its open attempts. A run that has ended is left alone."""
    _engine(Path(repo)).stop(run_id, reason=reason)


def recover(repo, run_id, *, rebuild=False) -> None:
    """Close open attempts as interrupted. With rebuild, first rebuild run.json from the last run_snapshot event."""
    run_dir = _ref(Path(repo), run_id).run_dir
    lock = state.acquire_lock(run_dir, "cli")
    try:
        closed = usage_mod.close_open_attempts(run_dir)
        if rebuild:
            state.write_run(run_dir, state.rebuild_run(run_dir), lock=lock)
        state.append_event(run_dir, "run_recovered", rebuild=rebuild, attempts_closed=len(closed))
    finally:
        state.release(lock)


# ---- reporting and housekeeping --------------------------------------------------------------------------------

def usage(repo, run_id=None, since=None) -> UsageReport:
    """Token totals per observed model, for one run or every run of this repo. `since` drops earlier days."""
    repo = Path(repo)
    if run_id is not None:
        dirs = [_ref(repo, run_id).run_dir]
    else:
        key = state.repo_key(repo, load_config(repo))
        dirs = [r.run_dir for r in state.list_runs(state.factory_home(), key=key)]
    return usage_mod.summarize(dirs, since=since)


def gc(repo, *, apply=False) -> GcPlan:
    """The housekeeping plan. With apply, carry it out; the plan is returned either way."""
    repo = Path(repo)
    cfg = load_config(repo)
    plan = housekeeping.plan(state.factory_home(), cfg, now=SystemClock().now(), prs=default_prs(repo, cfg))
    if apply:
        housekeeping.apply(plan)
    return plan


def doctor(repo: Path | None, *, as_scheduler: bool = False) -> list[CheckResult]:
    """Module 3's checks, then the skills lock and pack size of 10, the toolchain checks of 17A for a repo whose
    settings load, and the sandbox and harness checks of 9. Module 3 cannot call 9, 10 or 17A, because they depend on
    3, so this driver composes them. The module 9 checks run on every call (owner decision D2, 2026-11-22)."""
    checks = kit.doctor(repo, as_scheduler=as_scheduler)
    checks.extend(_harness_checks(as_scheduler))
    if repo is not None and all(c.ok for c in checks if c.name == "repo-config") and any(c.name == "repo-config" for c in checks):
        from . import skills
        from .toolchains import doctor_checks
        try:
            cfg = load_config(repo)
            checks.append(_problems_check("skills-lock", skills.verify_lock(repo), "the pinned skills match the lock"))
            checks.append(_problems_check("practice-packs", skills.oversized_packs(repo, cfg), "every pack is within its line limit"))
            checks.extend(doctor_checks(repo, cfg))
        except FactoryError as e:
            checks.append(CheckResult("toolchains", False, e.message, e.hint))
    return checks


def _harness_checks(as_scheduler: bool) -> list[CheckResult]:
    """Module 9: `srt` and its canary, then the Claude binary and credentials, then, only when those pass, the Claude
    sandbox canary and the isolation probe, which spend one short model call each. A call with no binary or no
    credentials could only fail, so it is not made and the failing check says why. With `as_scheduler` the Claude
    checks see the short environment cron gives a job; `srt` and Node still come from this process's PATH."""
    from tempfile import TemporaryDirectory

    from .adapters.worker import claude as claude_mod
    from .adapters.worker import sandbox
    from .loadcfg import factory_home

    out = [sandbox.check_srt()]
    home = factory_home()
    if out[0].ok:
        (home / "tmp").mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=home / "tmp", prefix="doctor-") as d:
            worktree, task_dir = Path(d) / "worktree", Path(d) / "work"
            worktree.mkdir()
            task_dir.mkdir()
            out.append(sandbox.canary_srt(worktree, task_dir, home))
    environ = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "")} if as_scheduler else None
    adapter = ClaudeAdapter(environ)
    try:
        conf = _claude_conf(environ)
        first = adapter.check(conf)
    except FactoryError as e:  # an unset ${VAR:?message} in the harness env: report it, keep the other checks
        out.append(CheckResult("claude", False, e.message, e.hint))
        return out
    out.append(first)
    if first.ok:
        out.append(claude_mod.canary_claude(conf, environ=environ, factory=home))
        (home / "tmp").mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=home / "tmp", prefix="doctor-probe-") as d:
            worktree, task_dir = Path(d) / "worktree", Path(d) / "work"
            worktree.mkdir()
            task_dir.mkdir()
            out.append(claude_mod.probe_isolation(conf, worktree, task_dir, environ=environ, factory=home))
    return out


def _claude_conf(environ: Mapping[str, str] | None):
    """The Claude harness settings from the machine file, or the defaults the engine itself starts workers with."""
    from .adapters.worker.base import HarnessConfig
    from .loadcfg import resolve_harness
    cfg = load_config(None)  # the machine file always comes from the real FACTORY_HOME, the same home the canaries use
    if "claude" in (cfg.machine.get("harnesses") or {}):
        return resolve_harness(cfg, "claude", env=os.environ if environ is None else environ)
    return HarnessConfig("claude", None, [], {})


def _problems_check(name: str, problems: list, ok_detail: str) -> CheckResult:
    if not problems:
        return CheckResult(name, True, ok_detail, "")
    return CheckResult(name, False, "; ".join(p.message for p in problems), problems[0].hint)


def run_engine_env(run_id: str, *, home: Path, env: Mapping[str, str]) -> dict[str, str]:
    """The environment that makes `python -m factory_engine` run the run's own engine: its kit snapshot's engine
    folder goes first on PYTHONPATH. Raises kit.no_engine when that folder is missing (ADR 2026-11-20-which-engine-serves-each-repo).
    """
    ref = state.find_run(home, run_id)
    if ref is None:
        raise FactoryError("config.invalid", f"no run named {run_id!r}", hint="factory status lists the runs in this repo")
    kit_hash = json.loads((ref.run_dir / "run.json").read_text())["kit_hash"]
    engine = home / "kits" / kit_hash / "factory" / "engine"
    if not engine.is_dir():
        raise FactoryError("kit.no_engine",
                           f"run {run_id} uses kit {kit_hash}, whose engine folder {engine} is missing",
                           hint=f"add --installed-engine to run this one command on the installed engine")
    return {**env, "PYTHONPATH": os.pathsep.join(p for p in (str(engine), env.get("PYTHONPATH", "")) if p)}


def spawn_engine(repo, run_id) -> int | None:
    """Start `python -m factory_engine run <run>` in its own session, unless a live lock exists. Returns its pid.

    The child writes its output to ~/.factory/logs, so a detached run leaves a trail when nobody is watching.
    The child runs the engine in the run's own kit snapshot, not the installed one.
    """
    repo = Path(repo)
    run_dir = _ref(repo, run_id).run_dir
    if state.lock_status(run_dir) == "live":
        return None
    home = state.factory_home()
    env = run_engine_env(run_id, home=home, env=os.environ)
    logs = home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / f"engine-{run_id}.log", "ab") as log:
        proc = subprocess.Popen([sys.executable, "-m", "factory_engine", "run", run_id, "--repo", str(repo)],
                                cwd=str(repo), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
    return proc.pid
