"""One scheduled pass (module 6, "Scheduled ticks"): sync, start engines for runs that can move, resume dead ones.

A tick keeps no state of its own. It reads every run.json under the factory home, decides one action per run from
its status and lock, starts a detached engine for each run that can move, and writes tick.json. It never runs a
worker, so it returns within seconds.

A blocked run whose decision file holds an answer the engine has not yet acted on starts an engine too, which applies
the answer under the run lock (module 11). A blocked run whose file is pending or absent gets a reminder only.

A run whose pull request is open waits at its merge review. The tick reads that pull request (module 13, watch_pr) and
starts an engine only when GitHub has merged it, closed it, turned its CI red, or turned it green for the first time;
the engine then ends the run, routes it, or checks the merge rules again.
The tick itself writes no run state.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from factory_engine import api, decisions, delivery, filelock, notify, state
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
    reminded: list[str] = field(default_factory=list)
    repo_missing: list[str] = field(default_factory=list)
    synced: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    skipped_tick: bool = False


def decide(status: str, lock: str, repo_exists: bool, *, answered: bool = False, pr_changed: bool = False) -> str:
    """The action module 6's table gives for one run. Pure, so the table is tested without a file system.
    `answered` is true when a waiting run's decision file holds an answer the engine has not acted on: an
    awaiting_approval run's open stop, or a blocked run's blocked file. `pr_changed` is true when the run's open pull
    request was merged, closed or turned red, so its engine has something to do."""
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
    if status == "blocked" and lock == "free" and answered:
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
    if not filelock.try_lock(fd):
        os.close(fd)
        return None
    return _TickLock(fd)


def _release_tick_lock(lock: _TickLock) -> None:
    try:
        filelock.unlock(lock.fd)
    finally:
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
    """True when a run waiting on its pull request has news: merged, closed, red CI, or green CI that the merge rules
    have not yet been checked against (owner decision D1, 2026-11-21). Pending CI, and green CI already checked, are no
    news. A failed read is logged in the report and counts as no news, so the next tick reads it again."""
    try:
        run = state.read_run(ref.run_dir)
        if not delivery.at_merge_review(run):
            return False
        pr = delivery.watch_pr(ref.run_dir, prs_for(ref.repo))
    except FactoryError as e:
        report.errors.append(f"{ref.run_id}: {e.code}: {e.message}")
        return False
    return pr.state != "open" or pr.ci == "red" or (pr.ci == "green" and not delivery.green_check_done(ref.run_dir))


def _default_prs(repo: Path) -> PullRequests:
    return api.default_prs(repo, load_config(repo))


def _default_tracker(repo: Path):
    return api.default_tracker(repo, load_config(repo))


def _remind(ref: state.RunRef, now: datetime, tracker_for: Callable, report: TickReport) -> None:
    """A run that waits for a person has no engine, so the tick reminds them when a reminder is due (module 11). A
    failed channel is reported and never stops the tick."""
    try:
        sent = notify.remind(ref.run_dir, load_config(ref.repo), tracker_for(ref.repo), now=now.isoformat())
    except FactoryError as e:
        report.errors.append(f"{ref.run_id}: {e.code}: {e.message}")
        return
    if sent is None:
        return
    report.reminded.append(ref.run_id)
    for channel, why in sent.failed.items():
        report.errors.append(f"{ref.run_id}: could not tell {channel}: {why}")


def tick(cfg: Config, *, repos: list[Path], home: Path | None = None, spawn: Callable | None = None,
         now: datetime | None = None, prs_for: Callable[[Path], PullRequests] | None = None,
         tracker_for: Callable[[Path], object] | None = None) -> TickReport:
    """One pass. `cfg` is load_config(None): the machine part only. Each repo's own settings come from load_config(repo)
    where a step reads them (sync does). Takes the machine tick lock; a held lock returns at once with skipped_tick."""
    home = home or state.factory_home()
    spawn = spawn or api.spawn_engine
    prs_for = prs_for or _default_prs
    tracker_for = tracker_for or _default_tracker
    when = now or SystemClock().now()
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
            blocked = repo_exists and status == "blocked" and lock_state == "free"
            action = decide(status, lock_state, repo_exists,
                            answered=(waiting and _answered(ref)) or (blocked and _blocked_answered(ref, report)),
                            pr_changed=waiting and _pr_changed(ref, prs_for, report))
            if action == MISSING:
                report.repo_missing.append(ref.run_id)
                continue
            if action == NOTHING:
                if repo_exists and status in ("awaiting_approval", "blocked") and lock_state == "free":
                    _remind(ref, when, tracker_for, report)
                continue
            try:
                _start_or_resume(ref, action, report, spawn)
            except FactoryError as e:
                report.errors.append(f"{ref.run_id}: {e.code}: {e.message}")
        _write_tick_json(home, report, when)
        _log(home, "tick", started=report.started, resumed=report.resumed, skipped=report.skipped,
             reminded=report.reminded)
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


# Events that show the engine has already acted on the bytes of a decision file (module 11): the answer was applied,
# refused, or rejected before it was used. The tick starts no engine for those bytes again.
_ACTED_ON = frozenset({"blocked_answer_applied", "blocked_answer_refused", "decision_rejected", "decision_invalidated"})


def _blocked_answered(ref: state.RunRef, report: TickReport) -> bool:
    """True when a blocked run's decision file is approved, its packet is intact, it is a blocked packet, and no event
    shows the engine has acted on these bytes yet. A file that is pending, absent or not a blocked packet is no answer.
    A file that cannot be read is reported in the tick's errors, and the run is left alone. Writes nothing."""
    try:
        run = state.read_run(ref.run_dir)
        if run.stage is None:
            return False
        visit = decisions.latest_visit(run, run.stage)
        path = decisions.decision_path(ref.run_dir, run.stage, visit)
        if not path.is_file():
            return False
        doc = decisions.read_decision(ref.run_dir, run.stage, visit)
        packet, dec = doc["packet"], doc["decision"]
        if decisions.kind_of(packet) != "blocked" or dec["status"] != "approved":
            return False
        if decisions.hash_packet(packet) != packet["sha"]:
            return False
        content = hashlib.sha256(path.read_bytes()).hexdigest()
        acted = any(e.type in _ACTED_ON and e.data.get("content") == content
                    for e in state.read_events(ref.run_dir))
        return not acted
    except FactoryError as e:
        report.errors.append(f"{ref.run_id}: {e.code}: the blocked decision file cannot be read: {e.message}")
    except (OSError, UnicodeDecodeError) as e:
        report.errors.append(f"{ref.run_id}: config.invalid: the blocked decision file cannot be read: {e}")
    return False


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
