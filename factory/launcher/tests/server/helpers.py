"""Plain helpers for the dashboard tests (module 15). Fixtures live in conftest.py."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from factory_engine import decisions, state
from factory_engine.lock import acquire_lock, release
from factory_engine.types import AttentionItem, Request, Source, StageState
from factory_launcher.server.launcher import LauncherResult

PORT = 8765
HOST = f"127.0.0.1:{PORT}"
ORIGIN = f"http://127.0.0.1:{PORT}"
TOKEN = "test-token-123"


_DEFAULT = object()


class FakeLauncher:
    """Stands in for `factory <command> --json`. It records each argument list and returns a canned result."""

    def __init__(self, doc=_DEFAULT, returncode=0, stderr=""):
        self.calls: list[list[str]] = []
        self.doc = {"ok": True, "data": {}} if doc is _DEFAULT else doc
        self.returncode = returncode
        self.stderr = stderr

    def __call__(self, args):
        self.calls.append(list(args))
        return LauncherResult(self.doc, self.returncode, self.stderr)


def request(title="Login fails", ref="acme/report#42"):
    return Request(request_id="gh-42", source=Source("github", ref, title, "body", ["bug"], "alice", []),
                   body_sha="c91e07", repo="report", title=title, type="bug", type_source="label",
                   priority="high", acceptance=["401 with a refresh hint"])


def make_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir(parents=True, exist_ok=True)
    return repo


def make_run(home: Path, repo: Path, *, key: str = "github.com/acme/report", run_id: str = "fix-login-a1b2c",
             kit_hash: str = "kit-1", title: str = "Login fails"):
    """A run folder with request.json and run.json, status pending. Use set_run to change its state."""
    return state.init_run(home, repo, key, run_id, request(title), branch=run_id,
                          worktree=repo.parent / f"{run_id}-wt", kit_hash=kit_hash)


def set_run(ref, held, *, status="pending", stage="fix", attention=None, signals=None, hold=False,
            age: timedelta = timedelta(0), now: datetime | None = None, stages=None):
    """Write run.json the way the lock holder does. hold=True keeps the lock, so the run is `running` and live.
    age sets run.json's modification time to `age` before `now`, so tests can place a run in time."""
    run = state.read_run(ref.run_dir)
    run.status, run.stage = status, stage
    run.stages = stages if stages is not None else [StageState(stage, 1, "running", [], "t0", None)]
    run.attention = attention
    run.signals = signals
    lock = acquire_lock(ref.run_dir, "engine")
    try:
        state.write_run(ref.run_dir, run, lock=lock)
    finally:
        if hold:
            held.append(lock)
        else:
            release(lock)
    if now is not None:
        when = (now - age).timestamp()
        os.utime(ref.run_dir / "run.json", (when, when))


def attention_for(ref, *, kind="decision", stage="propose", summary="Approve the plan", page=None, since=None):
    return AttentionItem(kind=kind, run_id=ref.run_id, stage=stage,
                         since=since or "2026-11-15T09:00:00+00:00", summary=summary, page=page,
                         command=None if page else f"factory decide {ref.run_id} --packet 00000000")


def approval_page(ref) -> Path:
    """A real decision file and page for an approval stop, written by module 11."""
    decisions.request(ref.run_dir, "propose", 1, kind="approval")
    return decisions.page_path(ref.run_dir, "propose", 1)


def write_tick(home: Path, when: datetime, result: str = "2 runs started") -> None:
    (home / "tick.json").write_text(json.dumps({"last_tick": when.isoformat(timespec="seconds"), "result": result}))


def call(app, method, path, *, token=TOKEN, host=HOST, origin=None, body=None, headers=None):
    """One request through App.handle. token=None sends no token; origin=None sends no Origin."""
    hdrs = {"Host": host}
    if token is not None:
        hdrs["X-Factory-Token"] = token
    if origin is not None:
        hdrs["Origin"] = origin
    hdrs.update(headers or {})
    raw = b"" if body is None else json.dumps(body).encode()
    return app.handle(method, path, hdrs, raw)


def get_json(app, path, **kw):
    resp = call(app, "GET", path, **kw)
    return resp.status, json.loads(resp.body)


def state_doc(app):
    status, doc = get_json(app, "/api/state.json")
    assert status == 200
    return doc
