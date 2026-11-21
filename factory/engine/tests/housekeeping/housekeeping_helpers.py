"""Plain helpers for the module 17 tests. Fixtures stay in conftest.py; tests import these by their own module name."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gitops"))
from gitutil import run as git_run  # noqa: E402

from factory_engine import state  # noqa: E402
from factory_engine.clock import FakeClock  # noqa: E402
from factory_engine.types import Request, Source, TaskState  # noqa: E402


KEY = "local/repo"


def write_repo_config(repo: Path, text: str) -> None:
    """factory.yaml with the required base_branch (factory-config schema) plus the given keys."""
    (repo / ".factory" / "config").mkdir(parents=True, exist_ok=True)
    (repo / ".factory" / "config" / "factory.yaml").write_text(
        "base_branch: main\ntracker: file\nharness: claude\n" + text)


def request(run_id: str) -> Request:
    return Request(request_id=run_id, source=Source("cli", run_id, "Title", "body", [], None, []),
                   body_sha="abc123", repo="repo", title="Title", type="bug", type_source="cli",
                   priority=None, acceptance=["done"])


def set_event_times(run_dir: Path, when: datetime) -> None:
    """Every event gets one timestamp, so the run's end is `when`."""
    path = run_dir / "events.jsonl"
    lines = []
    for raw in path.read_text().splitlines():
        ev = json.loads(raw)
        ev["ts"] = when.isoformat()
        lines.append(json.dumps(ev, separators=(",", ":")))
    path.write_text("\n".join(lines) + "\n")


def make_run(home, repo, run_id, *, status, worktree, ended=None, kit="kit1", tasks=(), repo_path=None):
    """A run folder in the state layout. `tasks` is (task_id, status, worktree) for each task."""
    ref = state.init_run(home, repo_path or repo, KEY, run_id, request(run_id), branch=run_id,
                         worktree=worktree, kit_hash=kit)
    lock = state.acquire_lock(ref.run_dir, "test")
    run = state.read_run(ref.run_dir)
    run.status = status
    state.write_run(ref.run_dir, run, lock=lock)
    for task_id, task_status, task_wt in tasks:
        state.write_task(ref.run_dir, TaskState(task_id=task_id, stage="fix", status=task_status, attempt=1,
                                                restarts=0, task_base=None, worktree=task_wt, checkpoints=0),
                         lock=lock)
    state.release(lock)
    if ended is not None:
        set_event_times(ref.run_dir, ended)
    return ref.run_dir


def dirty(worktree: Path) -> None:
    (worktree / "wip.txt").write_text("uncommitted\n")


def branch_exists(repo: Path, name: str) -> bool:
    return bool(git_run(repo, "branch", "--list", name))


def days_ago(clock: FakeClock, days: int) -> datetime:
    return clock.now() - timedelta(days=days)
