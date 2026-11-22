"""State store (module 6A): run folders, run.json, task.json, events.jsonl, the lock, rebuild, and lookup.

Only the engine writes run and task state (module 6A). Workers write only into their own work/ folder.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import string
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from . import atomic
from .atomic import append_jsonl, read_jsonl, write_json_atomic
from .config import Config
from .errors import FactoryError
from .lock import Lock, lock_status as _lock_status
from .types import (AttentionItem, Event, InfraWait, PrRef, Request, Run, RunRef, Signals, Source, StageState,
                    TaskState)
from .validate import validate

SCHEMA_VERSION = 1
LockState = Literal["live", "free", "stale"]  # G2: defined here, the spec names it in lock_status


@dataclass
class HistoryRecord:
    """G2: one line of history.jsonl per finished run (module 17). Fields are the run's identity and outcome."""

    run_id: str
    repo_key: str
    status: str
    ended: str


@dataclass
class ScanResult:
    """G2: what RunScanner.scan found since the last scan (module 6A)."""

    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    repo_missing: list[str] = field(default_factory=list)
    reread: int = 0


def factory_home(env: Mapping[str, str] = os.environ) -> Path:
    return Path(env.get("FACTORY_HOME") or Path.home() / ".factory")


_HTTPS = re.compile(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$")
_SSH = re.compile(r"^(?:ssh://)?(?:[^@/]+@)?([^:/]+)[:/](.+?)(?:\.git)?/?$")


def _origin(repo: Path) -> str | None:
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                             capture_output=True, text=True, check=False)
    except OSError:
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def repo_key(repo: Path, cfg: Config) -> str:
    """Override (factory.yaml repo_key), else the origin remote as host/path (SSH and HTTPS alike), else
    local/<folder> (module 3)."""
    override = (cfg.repo or {}).get("repo_key")
    if override:
        return str(override)
    url = _origin(repo)
    if url:
        m = _HTTPS.match(url) or _SSH.match(url)
        if m:
            return f"{m.group(1).lower()}/{m.group(2).strip('/')}"
    return f"local/{repo.name}"


def run_dir(home: Path, key: str, run_id: str) -> Path:
    return home / "runs" / key / run_id


_ALPHABET = string.ascii_lowercase + string.digits


def new_run_id(title: str, exists: Callable[[str], bool]) -> str:
    """'<slug>-<5 chars>', unique in the whole home: the caller's `exists` checks every repo."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "run"
    for _ in range(1000):
        rid = f"{slug}-{''.join(secrets.choice(_ALPHABET) for _ in range(5))}"
        if not exists(rid):
            return rid
    raise FactoryError("state.locked", "could not find a free run id", hint="retry")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _run_to_doc(run: Run) -> dict:
    from dataclasses import asdict, is_dataclass
    from pathlib import PurePath

    def conv(v):
        if is_dataclass(v):
            return {k: conv(x) for k, x in asdict(v).items()}
        if isinstance(v, PurePath):
            return str(v)
        if isinstance(v, list):
            return [conv(x) for x in v]
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, tuple):
            return [conv(x) for x in v]
        return v

    doc = conv(run)
    doc["schema_version"] = SCHEMA_VERSION
    return doc


def init_run(home: Path, repo: Path, key: str, run_id: str, request: Request, *,
             branch: str | None, worktree: Path, kit_hash: str) -> RunRef:
    """Create the run folder with request.json and run.json (with repo_path and kit_hash). Fails if it exists."""
    d = run_dir(home, key, run_id)
    if d.exists():
        raise FactoryError("state.locked", f"run {run_id} already exists", hint="choose another run id")
    d.mkdir(parents=True)
    write_json_atomic(d / "request.json", {"schema_version": SCHEMA_VERSION, **_dataclass_doc(request)})
    run = Run(run_id=run_id, repo=repo.name, repo_key=key, repo_path=repo, request=request, workflow=None,
              branch=branch, worktree=worktree, status="pending", stage=None, stages=[], loops={}, attention=None,
              pr=None, signals=None, heartbeat=_now(), kit_hash=kit_hash, infra_wait=None,
              paths={"run_dir": str(d), "repo": str(repo), "worktree": str(worktree)})
    doc = _run_to_doc(run)
    write_json_atomic(d / "run.json", doc)
    append_event(d, "run_created", run_id=run_id)
    # Module 6, decision E1: creating the run is a change, so it writes a run_snapshot too. Without it a run whose
    # run.json is lost before its first engine change cannot be rebuilt.
    append_event(d, "run_snapshot", run=doc)
    return RunRef(repo=repo, repo_key=key, run_id=run_id, run_dir=d)


def _dataclass_doc(obj) -> dict:
    from dataclasses import asdict
    from pathlib import PurePath

    def conv(v):
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list):
            return [conv(x) for x in v]
        if isinstance(v, PurePath):
            return str(v)
        return v
    return conv(asdict(obj))


def read_run(run_dir: Path) -> Run:
    path = run_dir / "run.json"
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return rebuild_run(run_dir)
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise FactoryError("config.invalid", f"{path}: unknown schema_version {doc.get('schema_version')}",
                           hint="run factory recover --rebuild to rebuild run.json from events")
    validate(doc, "run", file=str(path))
    return _run_from_doc(doc)


def _attention_from_doc(doc: dict) -> AttentionItem:
    """run.json holds the page as text; the item carries it as a Path, as attention_for makes it."""
    page = doc.get("page")
    return AttentionItem(**{**doc, "page": Path(page) if page else None})


def _run_from_doc(doc: dict) -> Run:
    req = Request(
        request_id=doc["request"]["request_id"], source=Source(**doc["request"]["source"]),
        body_sha=doc["request"]["body_sha"], repo=doc["request"]["repo"], title=doc["request"]["title"],
        type=doc["request"]["type"], type_source=doc["request"]["type_source"], priority=doc["request"]["priority"],
        acceptance=doc["request"]["acceptance"])
    stages = [StageState(**s) for s in doc["stages"]]
    attention = _attention_from_doc(doc["attention"]) if doc.get("attention") else None
    pr = PrRef(**doc["pr"]) if doc.get("pr") else None
    signals = Signals(**doc["signals"]) if doc.get("signals") else None
    infra = InfraWait(**doc["infra_wait"]) if doc.get("infra_wait") else None
    return Run(run_id=doc["run_id"], repo=doc["repo"], repo_key=doc["repo_key"], repo_path=Path(doc["repo_path"]),
               request=req, workflow=doc["workflow"], branch=doc["branch"], worktree=Path(doc["worktree"]),
               status=doc["status"], stage=doc["stage"], stages=stages, loops=doc["loops"], attention=attention,
               pr=pr, signals=signals, heartbeat=doc["heartbeat"], kit_hash=doc["kit_hash"], infra_wait=infra,
               paths=doc.get("paths") or {})


def write_run(run_dir: Path, run: Run, *, lock: Lock) -> None:
    """Atomic and schema-checked. Refuses unless this process holds the lock (module 6A, module 3 rule)."""
    if not _owns(lock, run_dir):
        raise FactoryError("state.locked", f"this process does not hold the lock on {run_dir.name}",
                           hint="acquire the run lock before writing run state")
    doc = _run_to_doc(run)
    validate(doc, "run", file=str(run_dir / "run.json"))
    write_json_atomic(run_dir / "run.json", doc)
    # Decision E1 [snapshot-event]: a run_snapshot event follows each change and carries the whole run.
    # Its payload is Unspecified in the spec; this code uses the same run document under "run".
    append_event(run_dir, "run_snapshot", run=doc)


def _owns(lock: Lock, run_dir: Path) -> bool:
    return lock.path == run_dir / "lock"


def _task_path(run_dir: Path, task_id: str) -> Path:
    return run_dir / "tasks" / task_id / "task.json"


def task_dir(run_dir: Path, task_id: str) -> Path:
    d = run_dir / "tasks" / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_task(run_dir: Path, task_id: str) -> TaskState:
    doc = json.loads(_task_path(run_dir, task_id).read_text())
    validate(doc, "task", file=str(_task_path(run_dir, task_id)))
    return TaskState(**{k: (Path(v) if k == "worktree" and v else v) for k, v in doc.items() if k != "schema_version"})


def write_task(run_dir: Path, task: TaskState, *, lock: Lock) -> None:
    if not _owns(lock, run_dir):
        raise FactoryError("state.locked", f"this process does not hold the lock on {run_dir.name}",
                           hint="acquire the run lock before writing task state")
    from dataclasses import asdict
    doc = {"schema_version": SCHEMA_VERSION, **{k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(task).items()}}
    validate(doc, "task", file=str(_task_path(run_dir, task.task_id)))
    write_json_atomic(_task_path(run_dir, task.task_id), doc)


def append_event(run_dir: Path, event: str, **fields) -> None:
    """Any process may append. Each event is one whole line (atomic.append_jsonl), with a sequence number."""
    seq = len(read_jsonl(run_dir / "events.jsonl")) + 1
    rec = {"schema_version": SCHEMA_VERSION, "seq": seq, "ts": _now(), "type": event,
           "run_id": run_dir.name, "data": fields}
    append_jsonl(run_dir / "events.jsonl", rec)


def read_events(run_dir: Path, *, since: int = 0) -> list[Event]:
    return [Event(seq=e["seq"], ts=e["ts"], type=e["type"], run_id=e["run_id"], data=e["data"])
            for e in read_jsonl(run_dir / "events.jsonl") if e.get("seq", 0) > since]


def acquire_lock(run_dir: Path, owner: str) -> Lock:
    from .lock import acquire_lock as _acquire
    return _acquire(run_dir, owner)


def heartbeat(lock: Lock) -> None:
    from .lock import heartbeat as _hb
    _hb(lock)


def release(lock: Lock) -> None:
    from .lock import release as _rel
    _rel(lock)


def lock_status(run_dir: Path) -> LockState:
    return _lock_status(run_dir)  # type: ignore[return-value]


def rebuild_run(run_dir: Path) -> Run:
    """Decision E1 [snapshot-event]: rebuild from the last run_snapshot in events.jsonl. The other events are not
    read to rebuild. Heartbeat and conflict signals are not part of a rebuild and are left empty."""
    last_doc = None
    for rec in reversed(read_jsonl(run_dir / "events.jsonl")):
        if rec.get("type") == "run_snapshot":
            last_doc = rec["data"]["run"]
            break
    if last_doc is None:
        raise FactoryError("config.invalid", f"{run_dir}: events.jsonl holds no run_snapshot",
                           hint="a rebuild needs a run_snapshot event; the engine writes one after each change")
    doc = dict(last_doc)
    doc["heartbeat"] = ""
    doc["signals"] = None
    return _run_from_doc(doc)


def find_by_source(home: Path, key: str, ref: str, body_sha: str) -> str | None:
    """A run for the same source ref and body hash in this repo (dedup, module 4). None when none."""
    base = home / "runs" / key
    if not base.is_dir():
        return None
    for d in sorted(base.iterdir()):
        if not (d / "request.json").is_file():
            continue
        req = json.loads((d / "request.json").read_text())
        src = req.get("source", {})
        if src.get("ref") == ref and req.get("body_sha") == body_sha:
            return d.name
    return None


def find_run(home: Path, run_id: str) -> RunRef | None:
    runs = home / "runs"
    if not runs.is_dir():
        return None
    for d in runs.rglob(run_id):
        if d.is_dir() and d.name == run_id and (d / "run.json").is_file():
            key = str(d.parent.relative_to(runs))
            run = json.loads((d / "run.json").read_text())
            return RunRef(repo=Path(run["repo_path"]), repo_key=key, run_id=run_id, run_dir=d)
    return None


def list_runs(home: Path, *, key: str | None = None) -> list[RunRef]:
    runs = home / "runs"
    out: list[RunRef] = []
    if not runs.is_dir():
        return out
    for rj in runs.rglob("run.json"):
        d = rj.parent
        rel = d.parent.relative_to(runs)
        if key is not None and str(rel) != key:
            continue
        run = json.loads(rj.read_text())
        out.append(RunRef(repo=Path(run["repo_path"]), repo_key=str(rel), run_id=d.name, run_dir=d))
    return sorted(out, key=lambda r: (r.repo_key, r.run_id))


def history_append(home: Path, record: HistoryRecord) -> None:
    from dataclasses import asdict
    append_jsonl(home / "history.jsonl", {"schema_version": SCHEMA_VERSION, **asdict(record)})


class RunScanner:
    """Change-aware polling (module 6A): re-reads a run's files only when their time or size changed.

    A scan stats every run.json and parses only the ones whose mtime or size differ from the last scan, so a scan with
    no changes parses nothing. A run that cannot be read is skipped and reported on its own; it does not fail the scan.
    """

    def __init__(self, home: Path):
        self.home = home
        self._seen: dict[str, tuple[float, int]] = {}
        self._repo: dict[str, Path] = {}  # run folder -> repo_path from its last successful read

    def scan(self) -> ScanResult:
        out = ScanResult()
        now: dict[str, tuple[float, int]] = {}
        runs = self.home / "runs"
        for rj in sorted(runs.rglob("run.json")) if runs.is_dir() else []:
            d = rj.parent
            key = str(d)
            try:
                st = rj.stat()
            except OSError:
                continue
            stamp = (st.st_mtime, st.st_size)
            now[key] = stamp
            if key not in self._seen:
                out.added.append(d.name)
            elif self._seen[key] != stamp:
                out.changed.append(d.name)
            else:
                if key in self._repo and not self._repo[key].exists():
                    out.repo_missing.append(d.name)
                continue
            out.reread += 1
            try:
                repo = Path(json.loads(rj.read_text())["repo_path"])
            except (OSError, ValueError, KeyError):
                self._repo.pop(key, None)
                continue
            self._repo[key] = repo
            if not repo.exists():
                out.repo_missing.append(d.name)
        for key in self._seen:
            if key not in now:
                out.removed.append(Path(key).name)
                self._repo.pop(key, None)
        self._seen = now
        return out
