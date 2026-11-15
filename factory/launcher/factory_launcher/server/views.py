"""The documents the dashboard serves (module 15): the overview, one run's detail, a task log and scheduler health.

Reads go through the 6A, 11, 12 and 14 functions. Nothing here writes. A file that cannot be read becomes an unreadable
row or an error entry, never a failed page. read_task is used only for a folder that has task.json, because
task_dir() (called by read_usage and pending_notes) creates folders.
"""

from __future__ import annotations

import json
import re
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePath
from typing import Any

from factory_engine.decisions import try_read
from factory_engine.errors import FactoryError
from factory_engine.notes import tail_log
from factory_engine.state import lock_status, read_events, read_task
from factory_engine.types import AttentionItem, Run
from factory_engine.usage import summarize
from factory_engine.validate import validate

from .runs import Entry, RunIndex
from .settings import Settings

FINISHED = ("done", "failed", "aborted")
NOT_RESPONDING_SECONDS = 120  # display only: a live lock whose heartbeat is older than this shows "not responding"
LOG_LINES = 200
PAGE_FILE = re.compile(r"([A-Za-z0-9_-]+)\.([0-9]+)\.html")  # <stage>.<n>.html, module 11
DECISION_FILE = re.compile(r"([A-Za-z0-9_-]+)\.([0-9]+)\.yaml")
TASK_ID = re.compile(r"[A-Za-z0-9_-]+")


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _since_key(value: Any) -> tuple[int, float, str]:
    try:
        return (0, datetime.fromisoformat(value).timestamp(), str(value))
    except (TypeError, ValueError):
        return (1, 0.0, str(value))


def _heartbeat_age(run_dir: Path, now: datetime) -> float | None:
    try:
        return now.timestamp() - float(json.loads((run_dir / "lock").read_text())["heartbeat"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _display_status(run_dir: Path, status: str, now: datetime) -> str:
    """The run's status, with two derived states for a running run: stale (no process holds the lock, the rule the
    tick uses) and not responding (held, but the heartbeat is old). lock_status is only asked for running runs."""
    if status != "running":
        return status
    if lock_status(run_dir) == "stale":
        return "stale"
    age = _heartbeat_age(run_dir, now)
    if age is not None and age > NOT_RESPONDING_SECONDS:
        return "not responding"
    return status


def _hidden(status: str, updated: datetime, settings: Settings, now: datetime) -> bool:
    return status in FINISHED and now - updated > timedelta(days=settings.show_finished_days)


def _warning(run: Run) -> bool:
    """A conflict warning: the run is behind its base, or overlaps another run's files (module 7)."""
    return bool(run.signals and (run.signals.behind_base > 0 or run.signals.overlaps))


def _attention(entry: Entry, item: AttentionItem) -> dict:
    page = Path(item.page) if item.page else None
    page_url = None
    if page is not None and PAGE_FILE.fullmatch(page.name) and (entry.run_dir / "decisions" / page.name).is_file():
        page_url = f"/runs/{entry.run_id}/decisions/{page.name}"
    return {"kind": item.kind, "run_id": entry.run_id, "repo_key": entry.repo_key, "repo": entry.run.repo,
            "stage": item.stage, "since": item.since, "summary": item.summary, "command": item.command,
            "page_url": page_url, "page_path": str(page) if page else None}


def _row(entry: Entry, settings: Settings, now: datetime) -> dict:
    if entry.run is None:
        return {"run_id": entry.run_id, "repo_key": entry.repo_key, "updated": _iso(entry.updated),
                "unreadable": entry.error, "kit_hash": None, "status": None, "display_status": "unreadable", "stage": None,
                "title": None, "repo_missing": False, "warning": False, "hidden": False, "attention": None}
    run = entry.run
    return {
        "run_id": entry.run_id, "repo_key": entry.repo_key, "repo": run.repo, "repo_path": str(run.repo_path),
        "kit_hash": run.kit_hash, "title": run.request.title, "status": run.status,
        "display_status": _display_status(entry.run_dir, run.status, now), "stage": run.stage,
        "updated": _iso(entry.updated), "heartbeat": run.heartbeat, "unreadable": None,
        "repo_missing": not run.repo_path.exists(), "warning": _warning(run),
        "hidden": _hidden(run.status, entry.updated, settings, now),
        "attention": _attention(entry, run.attention) if run.attention else None,
    }


def tick_health(settings: Settings, now: datetime) -> dict:
    """Scheduler health from tick.json in the factory home. Warns when no tick has run for more than
    stale_after_ticks intervals. The file format is not in a schema (Unspecified): it needs `last_tick` (ISO 8601)
    and may hold `result`."""
    base = {"every_minutes": settings.tick_every_minutes, "stale_after_ticks": settings.stale_after_ticks}
    path = settings.home / "tick.json"
    if not path.is_file():
        return {**base, "last_tick": None, "result": None, "warning": True, "message": "no tick has been recorded yet"}
    try:
        doc = json.loads(path.read_text())
        last = datetime.fromisoformat(doc["last_tick"])
    except (OSError, ValueError, KeyError, TypeError):
        return {**base, "last_tick": None, "result": None, "warning": True, "message": "tick.json is unreadable"}
    if last.tzinfo is None:
        last = last.astimezone()
    age = (now - last).total_seconds()
    warning = age > settings.stale_after_ticks * settings.tick_every_minutes * 60
    message = f"last tick {round(age / 60)} min ago"
    if warning:
        message += (f"; no tick for more than {settings.stale_after_ticks} intervals of "
                    f"{settings.tick_every_minutes:g} min")
    return {**base, "last_tick": _iso(last), "result": doc.get("result"), "warning": warning, "message": message}


def build_state(index: RunIndex, settings: Settings, now: datetime) -> dict:
    """GET /api/state.json: every run (finished ones past show_finished_days are flagged hidden), the attention items
    oldest first, the counters and the scheduler health."""
    entries = index.scan()
    rows = [_row(e, settings, now) for e in sorted(entries, key=lambda e: (e.repo_key, e.run_id))]
    visible = [r for r in rows if not r["hidden"]]
    needs = sorted((r["attention"] for r in visible if r["attention"]), key=lambda a: _since_key(a["since"]))
    today = now.astimezone().date()
    counters = {
        "running": sum(r["display_status"] == "running" for r in visible),
        "needs_you": len(needs),
        "blocked": sum(r["display_status"] == "blocked" for r in visible),
        "conflict_warnings": sum(r["warning"] for r in visible),
        "done_today": sum(1 for e in entries if e.run and e.run.status == "done"
                          and e.updated.astimezone().date() == today),
    }
    return {"generated": _iso(now), "counters": counters, "attention": needs, "runs": rows,
            "tick": tick_health(settings, now),
            "settings": {"show_finished_days": settings.show_finished_days, "refresh_seconds": 5}}


def _decisions(run_dir: Path) -> list[dict]:
    out = []
    folder = run_dir / "decisions"
    for f in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        m = DECISION_FILE.fullmatch(f.name)
        page = f.with_suffix(".html")
        doc = try_read(f)  # None when the file is unreadable or fails the decision schema
        item = {"file": f.name, "stage": m.group(1) if m else None, "visit": int(m.group(2)) if m else None,
                "page": page.name if page.is_file() else None, "valid": doc is not None}
        if doc is not None:
            item.update(packet=doc["packet"], decision=doc["decision"])
        out.append(item)
    return out


def _tasks(run_dir: Path) -> list[dict]:
    out = []
    folder = run_dir / "tasks"
    for d in sorted(folder.iterdir()) if folder.is_dir() else []:
        if not (d / "task.json").is_file():
            continue
        try:
            out.append(_jsonable(read_task(run_dir, d.name)))
        except Exception as e:  # noqa: BLE001 - one bad task file is a row, not a failed page
            out.append({"task_id": d.name, "unreadable": str(e)})
    return out


def _paths(run: Run, run_dir: Path, tasks: list[dict]) -> list[dict]:
    out: list[dict] = []

    def add(label: str, value: Any) -> None:
        if value:
            out.append({"label": label, "value": str(value)})

    add("Repo", run.repo_path)
    add("Worktree", run.worktree)
    add("Branch", run.branch)
    for t in tasks:
        add(f"Task {t.get('task_id')} worktree", t.get("worktree"))
    add("Source", run.request.source.ref)
    for f in run.request.source.files:
        add("Source file", f)
    add("Run folder", run_dir)
    return out


def _request(run_dir: Path) -> dict | None:
    """request.json, checked against its schema. An invalid file is shown as an error, not as a request."""
    path = run_dir / "request.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text())
        validate(doc, "request", file=str(path))
        return {k: v for k, v in doc.items() if k != "schema_version"}
    except (OSError, ValueError, FactoryError) as e:
        return {"error": e.message if isinstance(e, FactoryError) else str(e)}


def _usage(run_dir: Path) -> dict:
    """Token totals for this run by observed model, repo and day (module 14). Read-only."""
    report = summarize([run_dir])
    return {"by_model": _jsonable(report.by_model), "by_repo": _jsonable(report.by_repo),
            "by_day": _jsonable(report.by_day)}


def _read_text(path: Path) -> tuple[Any, str | None]:
    """(parsed JSON, error). A missing file is (None, None)."""
    if not path.is_file():
        return None, None
    try:
        return json.loads(path.read_text()), None
    except (OSError, ValueError) as e:
        return None, str(e)


def build_run(entry: Entry, settings: Settings, now: datetime) -> dict:
    """GET /api/runs/<id>: the run, its request, paths, tasks, decisions, merge result, summary and events."""
    row = _row(entry, settings, now)
    if entry.run is None:
        return {**row, "paths": [{"label": "Run folder", "value": str(entry.run_dir)}], "tasks": [], "decisions": []}
    run = entry.run
    tasks = _tasks(entry.run_dir)
    merge, merge_error = _read_text(entry.run_dir / "merge.json")  # no schema yet: shown as read, not validated
    try:  # the queued notes are the note_queued events (module 12)
        events = [_jsonable(e) for e in read_events(entry.run_dir)]
        events_error = None
    except Exception as e:  # noqa: BLE001 - a bad events file is shown as an error, not a failed page
        events, events_error = [], str(e)
    notes = [{"task_id": e["data"].get("task_id"), "note_id": e["data"].get("note_id"),
              "by": e["data"].get("by"), "deny": e["data"].get("deny"), "ts": e["ts"]}
             for e in events if e["type"] == "note_queued"]
    summary_path = entry.run_dir / "summary.md"
    return {
        **row,
        "request": _request(entry.run_dir), "run": _jsonable(run), "workflow": run.workflow,
        "usage": _usage(entry.run_dir),
        "kit_hash": run.kit_hash, "stages": _jsonable(run.stages), "loops": run.loops,
        "paths": _paths(run, entry.run_dir, tasks), "tasks": tasks, "decisions": _decisions(entry.run_dir),
        "pr": _jsonable(run.pr), "signals": _jsonable(run.signals), "infra_wait": _jsonable(run.infra_wait),
        "merge": {"document": merge, "error": merge_error, "validated": False},
        "summary": summary_path.read_text(errors="replace") if summary_path.is_file() else None,
        "notes": notes, "events_error": events_error,
    }


def task_log(index: RunIndex, run_id: str, task_id: str) -> str | None:
    """GET /api/runs/<id>/tasks/<task>/log: the last 200 lines of worker.log. None when the run or task is unknown."""
    entry = index.get(run_id)
    if entry is None or not TASK_ID.fullmatch(task_id):
        return None
    task_dir = entry.run_dir / "tasks" / task_id
    if not (task_dir / "task.json").is_file():
        return None
    return tail_log(task_dir / "worker.log", LOG_LINES)


def decision_page(index: RunIndex, run_id: str, name: str) -> Path | None:
    """The file behind GET /runs/<id>/decisions/<stage>.<n>.html, or None when the run or the page is unknown."""
    entry = index.get(run_id)
    if entry is None or not PAGE_FILE.fullmatch(name):
        return None
    path = entry.run_dir / "decisions" / name
    return path if path.is_file() else None
