"""Token tracking (module 14): one usage record per attempt, written before the worker starts.

`tasks/<task>/usage.jsonl` holds the records. An attempt has a `started` line, then a full `ended` line, and the last
readable line for an attempt wins. A line is readable when it is a whole JSON object with an integer `attempt` and
every field of UsageRecord. Token counts and model names come from what the CLI reports, never from config; an
unknown count is null, never 0.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from .errors import FactoryError
from .state import append_event, read_events, task_dir
from .types import Run, UsageRecord

SCHEMA_VERSION = 1
EXITS = ("ok", "failed", "interrupted")
UNKNOWN = "unknown"
_ATTEMPT_IN_TEXT = re.compile(rb'"attempt"\s*:\s*(\d+)')


@dataclass
class ModelTotals:
    """G2: one row of a UsageReport. `attempts_without_count` counts attempts with no token count, separately from tokens."""

    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    attempts_without_count: int = 0
    minutes: float = 0.0


@dataclass
class UsageReport:
    """G2: totals grouped by observed model, by repo and by day (module 14). `total` counts each attempt once."""

    by_model: dict[str, ModelTotals] = field(default_factory=dict)
    by_repo: dict[str, ModelTotals] = field(default_factory=dict)
    by_day: dict[str, ModelTotals] = field(default_factory=dict)
    total: ModelTotals = field(default_factory=ModelTotals)


def _path(run_dir: Path, task_id: str) -> Path:
    return task_dir(run_dir, task_id) / "usage.jsonl"


def _doc(r: UsageRecord) -> dict:
    d = asdict(r)
    d["worktree"] = str(r.worktree)
    return {"schema_version": SCHEMA_VERSION, **d}


def _record(d: dict) -> UsageRecord:
    d = {k: v for k, v in d.items() if k != "schema_version"}
    d["worktree"] = Path(d["worktree"])
    return UsageRecord(**d)


def _append(path: Path, doc: dict) -> None:
    """Write one whole line in one call. A file whose last byte is not a newline (a torn line from a crash) gets a
    newline first, so the new line is not joined to the torn one and lost with it (module 14: durable)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    torn_tail = False
    if path.is_file() and path.stat().st_size > 0:
        with path.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            torn_tail = fh.read(1) != b"\n"
    data = (b"\n" if torn_tail else b"") + (json.dumps(doc, separators=(",", ":")) + "\n").encode()
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _readable(doc) -> bool:
    if not isinstance(doc, dict) or not _is_attempt_number(doc.get("attempt")):
        return False
    try:
        _record(doc)
    except (TypeError, KeyError, ValueError):
        return False
    return True


def _is_attempt_number(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number_of(piece: bytes, doc) -> int | None:
    """The attempt number an unreadable line carries, if any: from its JSON, else from its text (a torn line)."""
    if isinstance(doc, dict) and _is_attempt_number(doc.get("attempt")):
        return doc["attempt"]
    found = _ATTEMPT_IN_TEXT.search(piece)
    return int(found.group(1)) if found else None


def _read(run_dir: Path, task_id: str) -> tuple[dict[int, dict], list[tuple[int, int | None]]]:
    """Return the last readable line for each attempt, and each unreadable line as (line number, attempt or None).
    Line numbers are 1-based. The last piece of a file with no newline is torn, so it is unreadable."""
    path = _path(run_dir, task_id)
    if not path.is_file():
        return {}, []
    raw = path.read_bytes()
    pieces = raw.split(b"\n")
    latest: dict[int, dict] = {}
    unreadable: list[tuple[int, int | None]] = []
    for no, piece in enumerate(pieces, start=1):
        if not piece.strip():
            continue
        torn = no == len(pieces) and not raw.endswith(b"\n")
        try:
            doc = None if torn else json.loads(piece)
        except ValueError:
            doc = None
        if _readable(doc):
            latest[doc["attempt"]] = doc
        else:
            unreadable.append((no, _number_of(piece, doc)))
    return latest, unreadable


def _warn_unreadable(run_dir: Path, task_id: str, unreadable: list[tuple[int, int | None]]) -> None:
    """One `usage_unreadable` event per unreadable line, with the task id and line number. A line already reported
    is not reported again, so the event is written once however many attempts start after it. If the write fails, the
    warning is skipped and the attempt goes on."""
    reported = {e.data.get("line") for e in read_events(run_dir)
                if e.type == "usage_unreadable" and e.data.get("task_id") == task_id}
    for no, _ in unreadable:
        if no not in reported:
            try:
                append_event(run_dir, "usage_unreadable", task_id=task_id, line=no)
            except OSError:
                return  # a warning must not stop an attempt; the next start_attempt finds the line unreported and tries again


def start_attempt(run_dir: Path, run: Run, task_id: str, *, stage: str, harness: str, model_requested: str | None) -> int:
    """Write the `started` record before the worker launches (write-ahead) and return the attempt number.
    The number is one more than the highest attempt number seen, including in an unreadable line that carries one."""
    latest, unreadable = _read(run_dir, task_id)
    seen = [*latest, *(n for _, n in unreadable if n is not None)]
    attempt = 1 + max(seen, default=0)
    rec = UsageRecord(run_id=run.run_id, task_id=task_id, stage=stage, attempt=attempt, harness=harness,
                      model_requested=model_requested, models=[], input_tokens=None, output_tokens=None, total_tokens=None,
                      start=datetime.now().astimezone().isoformat(timespec="seconds"), end=None, exit="started",
                      repo=run.repo, branch=run.branch, worktree=run.worktree)
    _append(_path(run_dir, task_id), _doc(rec))
    _warn_unreadable(run_dir, task_id, unreadable)
    append_event(run_dir, "attempt_started", task_id=task_id, attempt=attempt, harness=harness)
    return attempt


def finish_attempt(run_dir: Path, task_id: str, attempt: int, *, exit: str, input_tokens: int | None,
                   output_tokens: int | None, models: list[str]) -> None:
    """Append the full `ended` line. Unknown counts stay null, never 0."""
    if exit not in EXITS:
        raise FactoryError("config.invalid", f"usage exit {exit!r} is not one of {', '.join(EXITS)}", hint="use ok, failed or interrupted")
    started = _latest(run_dir, task_id, attempt)
    if started is None:
        raise FactoryError("config.invalid", f"no started record for {task_id} attempt {attempt}", hint="start_attempt must run first")
    total = None if input_tokens is None and output_tokens is None else (input_tokens or 0) + (output_tokens or 0)
    started.update(exit=exit, input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total,
                   models=list(models), end=datetime.now().astimezone().isoformat(timespec="seconds"))
    _append(_path(run_dir, task_id), started)
    append_event(run_dir, "attempt_ended", task_id=task_id, attempt=attempt, exit=exit)


def _latest(run_dir: Path, task_id: str, attempt: int) -> dict | None:
    doc = _read(run_dir, task_id)[0].get(attempt)
    return dict(doc) if doc else None


def has_open_attempt(run_dir: Path) -> bool:
    """True when some attempt of the run is still `started`, so a crashed engine left it open. Reads only."""
    tasks = run_dir / "tasks"
    for tdir in sorted(tasks.iterdir()) if tasks.is_dir() else []:
        latest, _ = _read(run_dir, tdir.name)
        if any(latest[a]["exit"] == "started" for a in latest):
            return True
    return False


def close_open_attempts(run_dir: Path) -> list[tuple[str, int]]:
    """Mark every attempt still `started` as `interrupted`, with no token count (a crash cut it off)."""
    closed: list[tuple[str, int]] = []
    tasks = run_dir / "tasks"
    for tdir in sorted(tasks.iterdir()) if tasks.is_dir() else []:
        latest, _ = _read(run_dir, tdir.name)
        for attempt in sorted(latest):
            if latest[attempt]["exit"] == "started":
                finish_attempt(run_dir, tdir.name, attempt, exit="interrupted", input_tokens=None, output_tokens=None, models=[])
                closed.append((tdir.name, attempt))
    return closed


def read_usage(run_dir: Path, task_id: str) -> list[UsageRecord]:
    """One record per attempt: the last readable line for an attempt. A `started` record is returned with exit
    `started`. Reading writes nothing; an unreadable line is skipped."""
    latest, _ = _read(run_dir, task_id)
    return [_record(latest[attempt]) for attempt in sorted(latest)]


def _minutes(r: UsageRecord) -> float:
    if not r.end:
        return 0.0
    return max(0.0, (datetime.fromisoformat(r.end) - datetime.fromisoformat(r.start)).total_seconds() / 60)


def _add(t: ModelTotals, r: UsageRecord) -> None:
    t.attempts += 1
    t.minutes += _minutes(r)
    if r.total_tokens is None and r.input_tokens is None and r.output_tokens is None:
        t.attempts_without_count += 1
        return
    t.input_tokens += r.input_tokens or 0
    t.output_tokens += r.output_tokens or 0
    t.total_tokens += r.total_tokens if r.total_tokens is not None else (r.input_tokens or 0) + (r.output_tokens or 0)


def summarize(run_dirs: list[Path], *, since: date | None = None) -> UsageReport:
    """Totals per observed model, repo and day (module 14), and a `total` that counts each attempt once. An attempt
    with no observed model is under `unknown`; an attempt with several models is counted under each, with its tokens
    as recorded (the record holds one total, so the per-model split the harness reported is not stored)."""
    report = UsageReport()
    for run_dir in run_dirs:
        tasks = run_dir / "tasks"
        for tdir in sorted(tasks.iterdir()) if tasks.is_dir() else []:
            for r in read_usage(run_dir, tdir.name):
                if r.exit == "started":
                    continue  # an open attempt has no result yet
                day = r.start[:10]
                if since is not None and date.fromisoformat(day) < since:
                    continue
                _add(report.total, r)
                for model in (r.models or [UNKNOWN]):
                    _add(report.by_model.setdefault(model, ModelTotals()), r)
                _add(report.by_repo.setdefault(r.repo, ModelTotals()), r)
                _add(report.by_day.setdefault(day, ModelTotals()), r)
    return report
