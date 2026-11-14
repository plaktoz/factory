"""Token tracking (module 14): one usage record per attempt, written before the worker starts.

`tasks/<task>/usage.jsonl` holds the records. An attempt has a `started` line, then a full `ended` line, and the last
line for an attempt wins. Token counts and model names come from what the CLI reports, never from config; an unknown
count is null, never 0.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from .atomic import append_jsonl, read_jsonl
from .errors import FactoryError
from .state import append_event, read_run, task_dir
from .types import Run, UsageRecord

SCHEMA_VERSION = 1
EXITS = ("ok", "failed", "interrupted")
UNKNOWN = "unknown"


@dataclass
class ModelTotals:
    """G2: one row of a UsageReport. `unknown_tokens` counts attempts with no token count, separately from tokens."""

    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    attempts_without_count: int = 0
    minutes: float = 0.0


@dataclass
class UsageReport:
    """G2: totals grouped by observed model, by repo and by day (module 14)."""

    by_model: dict[str, ModelTotals] = field(default_factory=dict)
    by_repo: dict[str, ModelTotals] = field(default_factory=dict)
    by_day: dict[str, ModelTotals] = field(default_factory=dict)


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


def start_attempt(run_dir: Path, run: Run, task_id: str, *, stage: str, harness: str, model_requested: str | None) -> int:
    """Write the `started` record before the worker launches (write-ahead) and return the attempt number."""
    attempt = 1 + max((r.attempt for r in read_usage(run_dir, task_id)), default=0)
    rec = UsageRecord(run_id=run.run_id, task_id=task_id, stage=stage, attempt=attempt, harness=harness,
                      model_requested=model_requested, models=[], input_tokens=None, output_tokens=None, total_tokens=None,
                      start=datetime.now().astimezone().isoformat(timespec="seconds"), end=None, exit="started",
                      repo=run.repo, branch=run.branch, worktree=run.worktree)
    append_jsonl(_path(run_dir, task_id), _doc(rec))
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
    append_jsonl(_path(run_dir, task_id), started)
    append_event(run_dir, "attempt_ended", task_id=task_id, attempt=attempt, exit=exit)


def _latest(run_dir: Path, task_id: str, attempt: int) -> dict | None:
    found = None
    for line in read_jsonl(_path(run_dir, task_id)):
        if line.get("attempt") == attempt:
            found = line  # the last line for an attempt wins
    return dict(found) if found else None


def close_open_attempts(run_dir: Path) -> list[tuple[str, int]]:
    """Mark every attempt still `started` as `interrupted`, with no token count (a crash cut it off)."""
    closed: list[tuple[str, int]] = []
    tasks = run_dir / "tasks"
    for tdir in sorted(tasks.iterdir()) if tasks.is_dir() else []:
        latest: dict[int, dict] = {}
        for line in read_jsonl(tdir / "usage.jsonl"):
            latest[line["attempt"]] = line
        for attempt, line in sorted(latest.items()):
            if line["exit"] == "started":
                finish_attempt(run_dir, tdir.name, attempt, exit="interrupted", input_tokens=None, output_tokens=None, models=[])
                closed.append((tdir.name, attempt))
    return closed


def read_usage(run_dir: Path, task_id: str) -> list[UsageRecord]:
    """One record per attempt: the last line for an attempt. A `started` record is returned with exit `started`."""
    latest: dict[int, dict] = {}
    for line in read_jsonl(_path(run_dir, task_id)):
        latest[line["attempt"]] = line
    out = []
    for attempt in sorted(latest):
        try:
            out.append(_record(latest[attempt]))
        except (TypeError, KeyError):
            continue  # an unreadable line is recorded as missing, never a block (module 14: errors)
    return out


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
    """Totals per observed model, repo and day (module 14). An attempt with no observed model is under `unknown`;
    an attempt with several models is counted under each, with its tokens as recorded (the record holds one total,
    so the per-model split the harness reported is not stored: Unspecified in the spec)."""
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
                for model in (r.models or [UNKNOWN]):
                    _add(report.by_model.setdefault(model, ModelTotals()), r)
                _add(report.by_repo.setdefault(r.repo, ModelTotals()), r)
                _add(report.by_day.setdefault(day, ModelTotals()), r)
    return report
