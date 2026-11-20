"""One scheduled pass (module 6, "Scheduled ticks"): sync, start engines for runs that can move, resume dead ones.

A tick keeps no state of its own. It reads every run.json under the factory home, decides one action per run from
its status and lock, starts a detached engine for each run that can move, and writes tick.json. It never runs a
worker, so it returns within seconds.

A run whose pull request is open waits at its merge review. The tick reads that pull request (module 13, watch_pr) and
starts an engine only when GitHub has merged it, closed it or turned its CI red; the engine then ends or routes the run.
The tick itself writes no run state.
"""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from factory_engine import api, decisions, delivery, state
from factory_engine.clock import SystemClock
from factory_engine.config import Config
from factory_engine.errors import FactoryError
from factory_engine.loadcfg import load_config
from factory_engine.prs import PullRequests

# What a tick does with each run, from its status and its lock (module 6, "How a tick finds and judges runs").
START = "start"
RESUME = "resume"
NOTHING = "nothing"
MISSING = "repo missing"

TICK_LOCK = "tick.lock"
TICK_JSON = "tick.json"


@dataclass
class TickReport:
    """What one tick did. Written to tick.json as `result`."""

    started: list[str] = field(default_factory=list)
    resumed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    repo_missing: list[str] = field(default_factory=list)
    synced: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    skipped_tick: bool = False


def decide(status: str, lock: str, repo_exists: bool, *, answered: bool = False, pr_changed: bool = False) -> str:
    """The action module 6's table gives for one run. Pure, so the table is tested without a file system.
    `answered` is true when an awaiting_approval run's decision file holds an answer. `pr_changed` is true when the
    run's open pull request was merged, closed or turned red, so its engine has something to do."""
    if not repo_exists:
        return MISSING
    if status in ("done", "failed", "aborted"):
        return NOTHING
    if status == "pending" and lock == "free":
        return START
    if status == "running" and lock == "stale":
        return RESUME
    if status == "awaiting_approval" and lock == "free" and (answered or pr_changed):
        return START
    if status == "retrying" and lock == "free":
        return START
    return NOTHING


@dataclass
class _TickLock:
    fd: int


def _take_tick_lock(home: Path) -> _TickLock | None:
    """The machine-wide tick lock. None when another tick holds it, so the caller exits at once."""
    home.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(home / TICK_LOCK), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return _TickLock(fd)


def _release_tick_lock(lock: _TickLock) -> None:
    fcntl.flock(lock.fd, fcntl.LOCK_UN)
    os.close(lock.fd)


def _log(home: Path, event: str, **fields) -> None:
    logs = home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    line = {"ts": SystemClock().now().isoformat(), "event": event, **fields}
    with open(logs / "tick.log", "a") as f:
        f.write(json.dumps(line, default=str) + "\n")


def _sync_repos(repos: list[Path], report: TickReport) -> None:
    """Read each repo's sources once and create runs for new requests. Starts no engine; the run loop does that."""
    for repo in repos:
        try:
            created = api.sync(repo).created
            report.synced[str(repo)] = [r.run_id for r in created]
        except FactoryError as e:
            report.errors.append(f"sync {repo}: {e.code}: {e.message}")


def _start_or_resume(ref: state.RunRef, action: str, report: TickReport, spawn: Callable) -> None:
    if action == START:
        pid = spawn(ref.repo, ref.run_id)
        if pid is None:
            report.skipped.append(ref.run_id)
        else:
            report.started.append(ref.run_id)
    elif action == RESUME:
        pid = spawn(ref.repo, ref.run_id)
        if pid is None:
            report.skipped.append(ref.run_id)
        else:
            report.resumed.append(ref.run_id)


def _pr_changed(ref: state.RunRef, prs_for: Callable[[Path], PullRequests], report: TickReport) -> bool:
    """True when a run waiting on its pull request has news: merged, closed or red CI. Open with green or pending CI is
    no news. A failed read is logged in the report and counts as no news, so the next tick reads it again."""
    try:
        run = state.read_run(ref.run_dir)
        if not delivery.at_merge_review(run):
            return False
        pr = delivery.watch_pr(ref.run_dir, prs_for(ref.repo))
    except FactoryError as e:
        report.errors.append(f"{ref.run_id}: {e.code}: {e.message}")
        return False
    return pr.state != "open" or pr.ci == "red"


def _default_prs(repo: Path) -> PullRequests:
    return api.default_prs(repo, load_config(repo))


def tick(cfg: Config, *, repos: list[Path], home: Path | None = None, spawn: Callable | None = None,
         now: datetime | None = None, prs_for: Callable[[Path], PullRequests] | None = None) -> TickReport:
    """One pass. `cfg` is load_config(None): the machine part only. Each repo's own settings come from load_config(repo)
    where a step reads them (sync does). Takes the machine tick lock; a held lock returns at once with skipped_tick."""
    home = home or state.factory_home()
    spawn = spawn or api.spawn_engine
    prs_for = prs_for or _default_prs
    report = TickReport()
    lock = _take_tick_lock(home)
    if lock is None:
        report.skipped_tick = True
        _log(home, "tick_skipped")
        return report
    try:
        _sync_repos([Path(r) for r in repos], report)
        for ref in state.list_runs(home):
            repo_exists = ref.repo.is_dir()
            status, lock_state = _status_and_lock(ref)
            waiting = repo_exists and status == "awaiting_approval" and lock_state == "free"
            action = decide(status, lock_state, repo_exists,
                            answered=waiting and _answered(ref),
                            pr_changed=waiting and _pr_changed(ref, prs_for, report))
            if action == MISSING:
                report.repo_missing.append(ref.run_id)
                continue
            if action == NOTHING:
                continue
            try:
                _start_or_resume(ref, action, report, spawn)
            except FactoryError as e:
                report.errors.append(f"{ref.run_id}: {e.code}: {e.message}")
        _write_tick_json(home, report, now or SystemClock().now())
        _log(home, "tick", started=report.started, resumed=report.resumed, skipped=report.skipped)
        return report
    finally:
        _release_tick_lock(lock)


def _answered(ref: state.RunRef) -> bool:
    """True when the open stop of an awaiting_approval run has an answer on disk, so an engine can carry on."""
    run = state.read_run(ref.run_dir)
    stage = next((s.id for s in run.stages if s.status == "awaiting_approval"), run.stage)
    if stage is None:
        return False
    doc = decisions.try_read(decisions.decision_path(ref.run_dir, stage, decisions.latest_visit(run, stage)))
    return doc is not None and doc["decision"]["status"] != "pending"


def _status_and_lock(ref: state.RunRef) -> tuple[str, str]:
    try:
        status = json.loads((ref.run_dir / "run.json").read_text()).get("status", "")
    except (OSError, ValueError):
        return "", "free"
    return status, state.lock_status(ref.run_dir)


def _write_tick_json(home: Path, report: TickReport, when: datetime) -> None:
    doc = {"last_tick": when.isoformat(), "result": asdict(report)}
    tmp = home / (TICK_JSON + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, default=str) + "\n")
    os.replace(tmp, home / TICK_JSON)
