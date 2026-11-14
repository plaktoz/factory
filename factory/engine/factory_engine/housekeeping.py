"""Housekeeping (module 17): the gc plan, its apply, and the cleanups the engine calls after a join or a merge.

Only paths a run recorded are removed: `worktree` in run.json and in each task.json, inside the worktree root or
the factory home. An active or blocked run is never touched, and neither is a run whose engine holds its lock.
Retention and cleanup_check come from each run's own repo (its factory.yaml), read with the given factory home.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from . import gitops, state
from .atomic import read_jsonl
from .config import Config
from .errors import FactoryError
from .gitops import delete_branch, remove_worktree
from .loadcfg import load_config
from .types import Run

ENDED = ("done", "failed", "aborted")
FAILED = ("failed", "aborted")
CHECK_TIMEOUT_S = 300
MB = 1024 * 1024
RETENTION_DEFAULTS = {"archive_after_days": 7, "delete_archive_after_days": 90, "keep_failed_days": 14,
                      "worker_log_max_mb": 50, "auto_gc": False}
# Files the engine writes into a worktree and keeps out of git (module 3, module 10). They never make it dirty.
ENGINE_OWNED_FILES = (".factory-run.json",)
ENGINE_OWNED_PREFIXES = (".claude/skills/factory-", ".agents/skills/factory-")
APPLY_ORDER = {"worktree": 0, "archive": 1, "archive_delete": 2, "kit": 3, "worker_log": 4}


@dataclass
class GcItem:
    kind: Literal["worktree", "archive", "archive_delete", "kit", "worker_log"]
    path: Path
    run_id: str | None = None
    cfg: Config | None = None       # the run's repo config: cleanup_check for a dirty worktree
    repo: Path | None = None        # the recorded repo, where a worktree's branch is deleted; None when it is gone
    dirty: bool = False             # a worktree with changes: cleanup_check decides at apply
    zip_path: Path | None = None    # archive: where the zip goes
    ended: str | None = None        # archive: when the run ended, for history.jsonl
    keep_bytes: int = 0             # worker_log: the newest part that is kept


@dataclass
class Skipped:
    path: Path
    run_id: str | None
    reason: str
    detail: str = ""


@dataclass
class Orphan:
    path: Path
    run_id: str | None
    reason: str


@dataclass
class Failed:
    path: Path
    message: str


@dataclass
class GcPlan:
    home: Path
    cfg: Config
    now: datetime
    items: list[GcItem] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    orphans: list[Orphan] = field(default_factory=list)


@dataclass
class GcReport:
    removed: list[str] = field(default_factory=list)
    archived: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    trimmed: list[str] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    orphans: list[Orphan] = field(default_factory=list)
    failed: list[Failed] = field(default_factory=list)


@dataclass
class _Snap:
    """A run as its folder or its archive records it."""
    run: dict
    tasks: list[dict]
    ended_at: datetime


@dataclass
class _Outcome:
    status: Literal["removed", "kept", "failed"]
    reason: str = ""
    detail: str = ""


def _retention(cfg: Config | None) -> dict:
    repo = (cfg.repo or {}) if cfg is not None else {}
    return {**RETENTION_DEFAULTS, **(repo.get("retention") or {})}


def _has_check(cfg: Config | None) -> bool:
    return bool(cfg is not None and cfg.repo and cfg.repo.get("cleanup_check"))


def _worktree_root(cfg: Config) -> Path:
    return Path((cfg.machine or {}).get("worktree_root") or Path.home() / ".factory" / "worktrees")


def _engine_owned(rel: str) -> bool:
    return rel in ENGINE_OWNED_FILES or rel.startswith(ENGINE_OWNED_PREFIXES)


def _is_dirty(path: Path) -> bool:
    """Uncommitted, untracked or ignored files, other than the engine's own. A worktree git cannot read is dirty."""
    r = gitops.git(path, "status", "--porcelain", "--ignored", "--untracked-files=all", check=False)
    if r.returncode != 0:
        return True
    return any(not _engine_owned(line[3:]) for line in r.stdout.splitlines() if line)


def _head_branch(path: Path) -> str | None:
    r = gitops.git(path, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    name = r.stdout.strip()
    return None if r.returncode != 0 or name in ("", "HEAD") else name


def _run_check(cfg: Config, path: Path) -> tuple[bool, str]:
    """cleanup_check (module 3): a list of strings, run in the worktree. Exit 0 means safe to remove."""
    cmd = (cfg.repo or {}).get("cleanup_check")
    if not cmd:
        return False, "cleanup_check is not set"
    try:
        r = subprocess.run(list(cmd), cwd=path, capture_output=True, text=True, timeout=CHECK_TIMEOUT_S)
    except FileNotFoundError:
        return False, f"cleanup_check command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, f"cleanup_check timed out after {CHECK_TIMEOUT_S}s"
    except OSError as e:
        return False, f"cleanup_check could not start: {e}"
    if r.returncode == 0:
        return True, ""
    return False, f"cleanup_check exited {r.returncode}: {(r.stdout + r.stderr).strip()[-500:]}"


def _remove_worktree_safely(cfg: Config | None, path: Path, repo: Path | None, *,
                            dirty: bool | None = None) -> _Outcome:
    """Remove a worktree and its checked-out branch. A dirty one goes only when cleanup_check exits 0 in it.

    With the repo gone, nothing can be checked or removed through git, so the worktree stays and is reported."""
    if repo is None or not repo.is_dir():
        return _Outcome("kept", "the repo is gone, so the worktree cannot be checked or removed through git")
    if dirty is None:
        dirty = _is_dirty(path)
    if dirty:
        if not _has_check(cfg):
            return _Outcome("kept", "not clean, and no cleanup_check is set")
        ok, detail = _run_check(cfg, path)
        if not ok:
            return _Outcome("kept", "not clean, and cleanup_check did not pass", detail)
    branch = _head_branch(path)
    try:
        remove_worktree(path, force=dirty)
    except FactoryError as e:
        return _Outcome("failed", e.message, e.hint)
    if branch:
        try:
            delete_branch(repo, branch)
        except FactoryError as e:
            return _Outcome("failed", f"worktree removed, branch {branch} kept: {e.message}", e.hint)
    return _Outcome("removed")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _ended_from_lines(lines: list[str], fallback: datetime) -> datetime:
    """The end of a run is the timestamp of its last event before housekeeping archived it. The `archived` event is
    written by gc itself, so it does not count; without another event, the fallback is used."""
    for raw in reversed(lines):
        try:
            ev = json.loads(raw)
            if ev.get("ts") and ev.get("type") != "archived":
                return datetime.fromisoformat(ev["ts"])
        except (ValueError, AttributeError):
            continue
    return fallback


def _read_folder(run_dir: Path) -> _Snap | None:
    try:
        run = _read_json(run_dir / "run.json")
        tasks = [_read_json(t) for t in sorted((run_dir / "tasks").glob("*/task.json"))]
    except (OSError, ValueError):
        return None
    events = (run_dir / "events.jsonl").read_text().splitlines() if (run_dir / "events.jsonl").is_file() else []
    fallback = datetime.fromtimestamp((run_dir / "run.json").stat().st_mtime, tz=timezone.utc)
    return _Snap(run, tasks, _ended_from_lines(events, fallback))


def _read_zip(zp: Path) -> _Snap | None:
    try:
        with zipfile.ZipFile(zp) as z:
            names = set(z.namelist())
            run = json.loads(z.read("run.json"))
            tasks = [json.loads(z.read(n)) for n in sorted(names) if n.startswith("tasks/") and n.endswith("/task.json")]
            events = z.read("events.jsonl").decode().splitlines() if "events.jsonl" in names else []
    except (OSError, ValueError, KeyError, UnicodeDecodeError, zipfile.BadZipFile):
        return None
    fallback = datetime.fromtimestamp(zp.stat().st_mtime, tz=timezone.utc)
    return _Snap(run, tasks, _ended_from_lines(events, fallback))


def _worktrees(snap: _Snap) -> list[Path]:
    out = [Path(snap.run["worktree"])] if snap.run.get("worktree") else []
    out += [Path(t["worktree"]) for t in snap.tasks if t.get("worktree")]
    return out


def _zip_path(home: Path, repo_key: str, run_id: str, ended: datetime) -> Path:
    return home / "archive" / repo_key / ended.strftime("%Y-%m") / f"{run_id}.zip"


def _markers(root: Path) -> list[Path]:
    """Run markers at worktree depth 1 to 3 under the worktree root (module 3: {root}/{repo}/{run_id})."""
    if not root.is_dir():
        return []
    found: list[Path] = []
    for depth in (1, 2, 3):
        found += root.glob("/".join(["*"] * depth) + "/.factory-run.json")
    return sorted(found)


def _archive_zips(home: Path) -> list[Path]:
    root = home / "archive"
    return sorted(p for p in root.rglob("*.zip") if p.is_file()) if root.is_dir() else []


class _RepoConfigs:
    """Each repo's own config, read with the given factory home and cached for one plan.

    The repo part is the run's own factory.yaml. The machine part is the caller's. A repo whose config is invalid
    raises FactoryError here, and the planner keeps its runs and says why."""

    def __init__(self, home: Path, base: Config):
        self.home = home
        self.base = base
        self._cache: dict[str, Config | FactoryError] = {}

    def get(self, repo: Path) -> Config:
        key = str(repo)
        if key not in self._cache:
            try:
                repo_part = load_config(repo, env={"FACTORY_HOME": str(self.home)}).repo if repo.is_dir() else None
                self._cache[key] = Config(machine=self.base.machine, repo=repo_part)
            except FactoryError as e:
                self._cache[key] = e
        out = self._cache[key]
        if isinstance(out, FactoryError):
            raise out
        return out

    def get_or_none(self, repo: Path) -> Config | None:
        try:
            return self.get(repo)
        except FactoryError:
            return None


def _due(snap: _Snap, cfg: Config, repo_gone: bool) -> tuple[datetime, datetime]:
    """(worktree due, archive due). A failed or aborted run keeps its worktrees keep_failed_days. A run whose repo
    is gone keeps everything keep_failed_days. Otherwise a run is archived after archive_after_days."""
    ret = _retention(cfg)
    failed = snap.run["status"] in FAILED
    worktree_days = ret["keep_failed_days"] if (failed or repo_gone) else ret["archive_after_days"]
    archive_days = ret["keep_failed_days"] if repo_gone else ret["archive_after_days"]
    return snap.ended_at + timedelta(days=worktree_days), snap.ended_at + timedelta(days=archive_days)


def _plan_worktree(p: GcPlan, path: Path, cfg: Config, repo: Path | None, run_id: str, *, due: bool,
                   seen: set[str]) -> None:
    """A due worktree is removed when clean, and handed to cleanup_check when not. One that is not due, or not
    removable, is reported while it stays, so a later gc lists it again."""
    key = str(path)
    if key in seen or not path.exists():
        return
    seen.add(key)
    if repo is not None and path.resolve() == repo.resolve():
        p.skipped.append(Skipped(path, run_id, "the recorded worktree is the repo itself; never removed"))
        return
    if repo is None:
        p.skipped.append(Skipped(path, run_id, "the repo is gone; the worktree cannot be checked or removed"))
        return
    dirty = _is_dirty(path)
    if not due:
        if dirty:
            p.skipped.append(Skipped(path, run_id, "not clean; kept until it is due or removed by hand"))
        return
    if dirty and not _has_check(cfg):
        p.skipped.append(Skipped(path, run_id, "not clean, and no cleanup_check is set",
                                 "the worktree stays until its files are compared or removed by hand"))
        return
    p.items.append(GcItem("worktree", path, run_id=run_id, cfg=cfg, repo=repo, dirty=dirty))


def _plan_ended_worktrees(p: GcPlan, snap: _Snap, cfg: Config, *, repo: Path, repo_gone: bool,
                          seen: set[str]) -> None:
    """The worktrees of an ended run, all due on the run's clock. gc has no pull request state, so a done run's own
    worktree is due with its archive; cleanup_after_merge removes it earlier when the merge hook runs."""
    run = snap.run
    worktree_due, _ = _due(snap, cfg, repo_gone)
    for path in _worktrees(snap):
        _plan_worktree(p, path, cfg, repo if not repo_gone else None, run["run_id"],
                       due=p.now >= worktree_due, seen=seen)


def _plan_active_run(p: GcPlan, snap: _Snap, seen: set[str]) -> None:
    """An active or blocked run is never touched. A joined task whose worktree is still dirty is reported, so a
    later gc lists what the join's cleanup could not remove."""
    for task in snap.tasks:
        if task.get("status") == "done" and task.get("worktree"):
            path = Path(task["worktree"])
            if path.exists() and str(path) not in seen and _is_dirty(path):
                seen.add(str(path))
                p.skipped.append(Skipped(path, snap.run["run_id"], "joined task, not clean; the run is still active"))


def _plan_folder_run(p: GcPlan, run_dir: Path, snap: _Snap, repos: _RepoConfigs, seen: set[str],
                     archived: set[str]) -> None:
    run = snap.run
    run_id, status = run["run_id"], run["status"]
    repo = Path(run["repo_path"])
    repo_gone = not repo.is_dir()
    if repo_gone:
        p.orphans.append(Orphan(run_dir, run_id, f"repo {repo} is gone"))
    if status == "pending":
        return
    if not Path(run["worktree"]).exists():
        p.orphans.append(Orphan(run_dir, run_id, f"recorded worktree {run['worktree']} is gone"))
    if status not in ENDED:
        _plan_active_run(p, snap, seen)
        return
    if state.lock_status(run_dir) == "live":
        p.skipped.append(Skipped(run_dir, run_id, "an engine holds the run lock; not touched"))
        return
    try:
        cfg = repos.get(repo)
    except FactoryError as e:
        p.skipped.append(Skipped(run_dir, run_id, f"{e.message}; the run is kept", e.hint))
        return
    _plan_ended_worktrees(p, snap, cfg, repo=repo, repo_gone=repo_gone, seen=seen)
    _, archive_due = _due(snap, cfg, repo_gone)
    if p.now >= archive_due:
        archived.add(run_id)
        p.items.append(GcItem("archive", run_dir, run_id=run_id, cfg=cfg, repo=repo,
                              zip_path=_zip_path(p.home, run["repo_key"], run_id, snap.ended_at),
                              ended=snap.ended_at.isoformat()))
        return
    cap = int(_retention(cfg)["worker_log_max_mb"]) * MB
    for log in sorted(run_dir.glob("tasks/*/worker.log")):
        if log.stat().st_size > cap:
            p.items.append(GcItem("worker_log", log, run_id=run_id, keep_bytes=cap))


def _plan_archived_run(p: GcPlan, zp: Path, snap: _Snap, repos: _RepoConfigs, seen: set[str]) -> None:
    """A run already archived keeps reporting its worktrees that are not removed (module 17, reported every gc)."""
    run = snap.run
    repo = Path(run["repo_path"])
    repo_gone = not repo.is_dir()
    cfg = repos.get_or_none(repo)
    if cfg is None:
        p.skipped.append(Skipped(zp, run["run_id"], "its repo config is invalid; the worktrees are kept"))
        return
    _plan_ended_worktrees(p, snap, cfg, repo=repo, repo_gone=repo_gone, seen=seen)


def plan(home: Path, cfg: Config, *, now: datetime) -> GcPlan:
    """What gc would do. Nothing is changed here, except that git is asked whether worktrees are clean."""
    p = GcPlan(home=home, cfg=cfg, now=now)
    repos = _RepoConfigs(home, cfg)
    seen: set[str] = set()
    archived: set[str] = set()
    folder_snaps: list[_Snap] = []
    unreadable = False
    for ref in state.list_runs(home):
        snap = _read_folder(ref.run_dir)
        if snap is None:
            unreadable = True
            p.skipped.append(Skipped(ref.run_dir, ref.run_id, "run.json cannot be read; the run is kept"))
            continue
        folder_snaps.append(snap)
        _plan_folder_run(p, ref.run_dir, snap, repos, seen, archived)

    zip_run_ids: set[str] = set()
    for zp in _archive_zips(home):
        snap = _read_zip(zp)
        if snap is None:
            p.skipped.append(Skipped(zp, None, "archive cannot be read; it is kept"))
            continue
        zip_run_ids.add(snap.run["run_id"])
        _plan_archived_run(p, zp, snap, repos, seen)
        written = datetime.fromtimestamp(zp.stat().st_mtime, tz=timezone.utc)
        delete_after = int(_retention(repos.get_or_none(Path(snap.run["repo_path"]))
                                      or cfg)["delete_archive_after_days"])
        if now - written >= timedelta(days=delete_after):
            p.items.append(GcItem("archive_delete", zp, run_id=snap.run["run_id"]))

    for marker in _markers(_worktree_root(cfg)):
        try:
            doc = _read_json(marker)
        except (OSError, ValueError):
            p.orphans.append(Orphan(marker.parent, None, "its .factory-run.json cannot be read"))
            continue
        run_id = doc.get("run_id")
        if (Path(doc.get("run_dir", "")) / "run.json").is_file() or run_id in zip_run_ids:
            continue
        p.orphans.append(Orphan(marker.parent, run_id, "its run folder is gone and no archive records it"))

    kits = home / "kits"
    if unreadable:
        p.skipped.append(Skipped(kits, None, "a run.json cannot be read; kit snapshots are kept"))
    elif kits.is_dir():
        used = {s.run["kit_hash"] for s in folder_snaps if s.run["run_id"] not in archived}
        for d in sorted(kits.iterdir()):
            if d.is_dir() and d.name not in used:
                p.items.append(GcItem("kit", d))
    return p


def _write_archive(run_dir: Path, zip_path: Path) -> None:
    """Zip the run folder to a temporary file, check it against the folder, then move it into place.

    The lock file is left out: it belongs to the running process, not to the run's record."""
    files = {p: p.relative_to(run_dir).as_posix() for p in sorted(run_dir.rglob("*"))
             if p.is_file() and p.relative_to(run_dir).as_posix() != "lock"}
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = zip_path.with_name(zip_path.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for path, name in files.items():
                z.write(path, name)
        with zipfile.ZipFile(tmp) as z:
            if z.testzip() is not None or set(z.namelist()) != set(files.values()):
                raise OSError("archive does not list the run folder's files")
            for path, name in files.items():
                if z.read(name) != path.read_bytes():
                    raise OSError(f"archive differs from {name}")
        os.replace(tmp, zip_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _record_history(home: Path, doc: dict, ended: str | None) -> None:
    if any(r.get("run_id") == doc["run_id"] for r in read_jsonl(home / "history.jsonl")):
        return
    state.history_append(home, state.HistoryRecord(run_id=doc["run_id"], repo_key=doc["repo_key"],
                                                   status=doc["status"], ended=ended or ""))


def _archive(home: Path, item: GcItem, report: GcReport) -> None:
    run_dir = item.path
    if not run_dir.is_dir():
        return
    try:
        lock = state.acquire_lock(run_dir, "housekeeping")
    except FactoryError as e:
        report.skipped.append(Skipped(run_dir, item.run_id, "an engine holds the run lock; not archived", e.message))
        return
    try:
        doc = _read_json(run_dir / "run.json")
        if doc["status"] not in ENDED:
            report.skipped.append(Skipped(run_dir, item.run_id, "the run is no longer ended; not archived"))
            return
        if not any(e.get("type") == "archived" for e in read_jsonl(run_dir / "events.jsonl")):
            state.append_event(run_dir, "archived", archive=str(item.zip_path))
        _write_archive(run_dir, item.zip_path)
        _record_history(home, doc, item.ended)
        for child in sorted(run_dir.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
            else:
                child.unlink()
        run_dir.rmdir()
        report.archived.append(item.run_id or run_dir.name)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as e:
        report.failed.append(Failed(run_dir, f"not archived; the run folder is kept: {e}"))
    finally:
        state.release(lock)


def _apply_worktree(item: GcItem, report: GcReport) -> None:
    out = _remove_worktree_safely(item.cfg, item.path, item.repo, dirty=item.dirty)
    if out.status == "removed":
        report.removed.append(str(item.path))
    elif out.status == "kept":
        report.skipped.append(Skipped(item.path, item.run_id, out.reason, out.detail))
    else:
        report.failed.append(Failed(item.path, out.reason))


def _kits_in_use(home: Path) -> set[str]:
    """Kit hashes that a run folder still on disk uses. An unreadable run may use any kit, so it keeps them all."""
    used: set[str] = set()
    for ref in state.list_runs(home):
        try:
            used.add(_read_json(ref.run_dir / "run.json")["kit_hash"])
        except (OSError, ValueError, KeyError):
            used.add("*")
    return used


def _truncate(path: Path, keep: int) -> None:
    data = path.read_bytes()[-keep:]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def apply(plan: GcPlan) -> GcReport:
    """Carry the plan out in order: worktrees, archives, archive deletes, kits, then log trims.

    Each step reports its own failure and the rest continue. A kit is deleted only when no run folder left on disk
    uses it, so a kit is never removed under a run that is still there."""
    report = GcReport(skipped=list(plan.skipped), orphans=list(plan.orphans))
    for item in sorted(plan.items, key=lambda i: APPLY_ORDER[i.kind]):
        if item.kind == "worktree":
            _apply_worktree(item, report)
        elif item.kind == "archive":
            _archive(plan.home, item, report)
        elif item.kind == "archive_delete":
            try:
                item.path.unlink()
                report.deleted.append(str(item.path))
            except OSError as e:
                report.failed.append(Failed(item.path, f"could not delete the archive: {e}"))
        elif item.kind == "kit":
            used = _kits_in_use(plan.home)
            if "*" in used or item.path.name in used:
                report.skipped.append(Skipped(item.path, None, "a run folder still uses this kit snapshot"))
                continue
            try:
                shutil.rmtree(item.path)
                report.deleted.append(str(item.path))
            except OSError as e:
                report.failed.append(Failed(item.path, f"could not delete the kit: {e}"))
        else:
            try:
                _truncate(item.path, item.keep_bytes)
                report.trimmed.append(str(item.path))
            except OSError as e:
                report.failed.append(Failed(item.path, f"could not trim the log: {e}"))
    for repo in sorted({i.repo for i in plan.items if i.repo is not None and i.repo.is_dir()}):
        gitops.git(repo, "worktree", "prune", check=False)
    return report


def cleanup_after_join(repo: Path, cfg: Config, run: Run, task_ids: list[str]) -> None:
    """Called by 6B right after a join: each task worktree and its branch go, unless cleanup_check says no.

    A worktree that stays is listed by every later gc until it is removed."""
    for task_id in task_ids:
        for path in gitops._worktrees_on(repo, f"{run.run_id}--{task_id}"):
            _remove_worktree_safely(cfg, path, repo)


def cleanup_after_merge(repo: Path, cfg: Config, run: Run) -> None:
    """Called by 6B or tick once the pull request is merged: the run worktree and its local branch go."""
    if run.worktree.exists():
        _remove_worktree_safely(cfg, run.worktree, repo)
