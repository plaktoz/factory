"""The repo engine's driver functions (module 16): one function per command, each composing modules.

Only drivers compose modules and only drivers may import `engine.py`. The blocked-run actions of module 8 (retry,
goto, skip) change a run and start no worker, so they build an Engine with no worker adapter. `spawn_engine` is the
one function that starts work. Every other function that needs a worker, tracker or pull request takes the real
adapter from the `default_*` functions here, or one the caller passes to `engine_for`.
"""

from __future__ import annotations

import json
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
from .types import RunRef, Source
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
    plan = housekeeping.plan(state.factory_home(), load_config(repo), now=SystemClock().now())
    if apply:
        housekeeping.apply(plan)
    return plan


def run_engine_env(repo, run_id) -> dict[str, str]:
    """The environment that runs a command about `run_id` on the engine in the run's own kit snapshot (kit.no_engine if none)."""
    ref = _ref(Path(repo), run_id)
    kit_hash = json.loads((ref.run_dir / "run.json").read_text())["kit_hash"]
    return kit.engine_env(kit.snapshot_engine_dir(state.factory_home(), kit_hash),
                          subject=f"run {run_id} (kit {kit_hash})")


def spawn_engine(repo, run_id) -> int | None:
    """Start `python -m factory_engine run <run>` in its own session, unless a live lock exists. Returns its pid.

    The child writes its output to ~/.factory/logs, so a detached run leaves a trail when nobody is watching.
    """
    repo = Path(repo)
    run_dir = _ref(repo, run_id).run_dir
    if state.lock_status(run_dir) == "live":
        return None
    env = run_engine_env(repo, run_id)
    logs = state.factory_home() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / f"engine-{run_id}.log", "ab") as log:
        proc = subprocess.Popen([sys.executable, "-m", "factory_engine", "run", run_id, "--repo", str(repo)],
                                cwd=str(repo), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
    return proc.pid
