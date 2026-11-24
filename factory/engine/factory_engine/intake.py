"""Intake (module 4): read the sources, normalize each one into a request, dedupe, and create the run.

Every source becomes request.json before its run exists, because the run's name needs the title. Triage (triage.py)
picks the workflow later, inside the run. The run worktree and branch are reserved here and created by module 6B.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
import time
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from . import state
from .adapters.tracker.base import SYNC_LIMIT, TrackerAdapter
from .atomic import append_jsonl
from .config import Config
from .errors import FactoryError
from .gitops import snapshot_kit
from .paths import check_outside_repo, render
from .triage import TYPE_WORKFLOW
from .types import AttentionItem, Request, RunRef, Source
from .yamlio import load_yaml

SETTLE_SECONDS = 10  # a folder in the inbox is picked up after this long with no new file (module 4)
TERMINAL = ("done", "failed", "aborted")
_FACTORY_KEY = re.compile(r"(?:factory_status|factory_run|factory_error):")
_FRONT_MATTER = re.compile(r"\A---\n(?P<fm>.*?\n)?---\n", re.S)


@dataclass
class SyncReport:
    created: list[RunRef] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# --- markdown front matter ---

def _split(text: str) -> tuple[str | None, str]:
    """(front matter text, or None when the file has none; the body)."""
    m = _FRONT_MATTER.match(text)
    if not m:
        return None, text
    return m.group("fm") or "", text[m.end():]


def _front(text: str, where: str) -> tuple[dict, str]:
    fm_text, body = _split(text)
    if fm_text is None:
        return {}, body
    try:
        doc = load_yaml(fm_text, file=where) if fm_text.strip() else None
    except FactoryError as e:
        raise FactoryError("intake.invalid", e.message, hint="fix the front matter YAML at the line named") from e
    if doc is None:
        return {}, body
    if not isinstance(doc, dict):
        raise FactoryError("intake.invalid", f"{where}: front matter must be key: value pairs",
                           hint="write the front matter as key: value lines between two --- lines")
    return doc, body


def _heading(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _labels_of(fm: dict) -> list[str]:
    value = fm.get("labels")
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def _read_files(files: list[Path]) -> tuple[str, str, list[str]]:
    """Title (the first file's front matter title, else its first # heading), the combined body, and labels.

    A file whose front matter does not parse contributes its whole text as body. normalize reports the error."""
    title, labels, bodies = "", [], []
    for i, path in enumerate(files):
        text = path.read_text()
        try:
            fm, body = _front(text, str(path))
        except FactoryError:
            fm, body = {}, text
        if i == 0:
            title = str(fm.get("title") or "").strip() or _heading(body)
        for label in _labels_of(fm):
            if label not in labels:
                labels.append(label)
        if body.strip():
            bodies.append(body.strip())
    return title, "\n\n".join(bodies), labels


def _markdown_sources(repo: Path) -> list[Source]:
    inbox = repo / ".factory" / "inbox"
    if not inbox.is_dir():
        return []
    out: list[Source] = []
    for entry in sorted(inbox.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if entry.name == "processed":
                continue
            everything = [p for p in entry.iterdir() if p.is_file()]
            files = sorted(p for p in everything if p.suffix == ".md")
            if not files:
                continue
            newest = max([p.stat().st_mtime for p in everything] + [entry.stat().st_mtime])
            if time.time() - newest < SETTLE_SECONDS:
                continue  # still receiving files; the next sync picks it up whole
        elif entry.is_file() and entry.suffix == ".md":
            files = [entry]
        else:
            continue
        title, body, labels = _read_files(files)
        out.append(Source(type="markdown", ref=str(entry.relative_to(repo)), title=title, body=body,
                          labels=labels, author=None, files=files))
    return out


def read_sources(repo: Path, cfg: Config, tracker: TrackerAdapter,
                 kinds: tuple[str, ...] = ("github", "markdown")) -> list[Source]:
    out: list[Source] = []
    if "github" in kinds:
        out.extend(tracker.list_new(None))
    if "markdown" in kinds:
        out.extend(_markdown_sources(repo))
    return out


# --- normalization ---

def _without_factory_keys(text: str) -> str:
    """The file with the factory's own status keys removed, so writing status never changes the body hash."""
    fm_text, body = _split(text)
    if fm_text is None:
        return text
    kept = [line for line in fm_text.splitlines(keepends=True) if not _FACTORY_KEY.match(line)]
    return "---\n" + "".join(kept) + "---\n" + body if kept else body


def _body_sha(source: Source) -> str:
    h = hashlib.sha256()
    if source.files:
        for path in sorted(source.files, key=lambda p: p.name):
            h.update(path.name.encode() + b"\0" + _without_factory_keys(path.read_text()).encode() + b"\0")
    else:
        h.update(source.body.encode())
    return h.hexdigest()[:6]


def _request_id(source: Source) -> str:
    if source.type == "github":
        m = re.search(r"#(\d+)$", source.ref)
        if m:
            return f"gh-{m.group(1)}"
    if source.type == "markdown":
        return "md-" + (re.sub(r"[^a-z0-9]+", "-", Path(source.ref).stem.lower()).strip("-") or "request")
    return source.ref


def normalize(source: Source, cfg: Config) -> Request:
    """Build the request. A missing title, an unknown type, or a malformed field raises intake.invalid with the reason."""
    title = (source.title or "").strip()
    if not title:
        hint = {"github": "give the issue a title", "markdown": "add title: to the front matter, or a # heading",
                "cli": "pass a title"}.get(source.type, "give the request a title")
        raise FactoryError("intake.invalid", f"{source.ref}: the request has no title", hint=hint)
    rtype, priority, acceptance = None, None, []
    for path in source.files:
        fm, _ = _front(path.read_text(), str(path))
        if rtype is None and fm.get("type") is not None:
            rtype = str(fm["type"]).strip()
        if priority is None and fm.get("priority") is not None:
            priority = str(fm["priority"]).strip()
        items = fm.get("acceptance")
        if items is not None:
            if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
                raise FactoryError("intake.invalid", f"{path}: acceptance must be a list of strings",
                                   hint="write acceptance as a list, one criterion per line")
            acceptance.extend(items)
    if rtype is not None and rtype not in TYPE_WORKFLOW:
        raise FactoryError("intake.invalid", f"{source.ref}: unknown type {rtype!r}",
                           hint=f"use one of {', '.join(TYPE_WORKFLOW)}")
    return Request(request_id=_request_id(source), source=source, body_sha=_body_sha(source), repo="",
                   title=title, type=rtype, type_source="front_matter" if rtype else None,
                   priority=priority, acceptance=acceptance)


# --- status written back to markdown files ---

def _set_front_matter(path: Path, updates: dict[str, str | None]) -> None:
    """Set keys in the front matter, adding it when missing. A None value removes the key. The rest is kept."""
    text = path.read_text()
    fm_text, body = _split(text)
    lines = [] if fm_text is None else fm_text.splitlines(keepends=True)
    for key, value in updates.items():
        lines = [line for line in lines if not line.startswith(f"{key}:")]
        if value is not None:
            lines.append(f"{key}: {value}\n")
    new = "---\n" + "".join(lines) + "---\n" + body if lines else body
    if new != text:
        path.write_text(new)


def _record_event(home: Path, key: str, event: str, **fields) -> None:
    """Events for a request that has no run yet go to the repo's intake log in the factory home."""
    append_jsonl(home / "intake" / key / "events.jsonl",
                 {"ts": _now(), "type": event, "data": fields})


def _front_lines(path: Path) -> list[str]:
    fm_text, _ = _split(path.read_text())
    return [] if fm_text is None else fm_text.splitlines()


def _already_marked(source: Source) -> bool:
    """True once the source shows a factory status: a status label on GitHub, or factory_run in a markdown file."""
    if source.type == "github":
        return any(label.startswith("factory:") for label in source.labels)
    return any(line.startswith("factory_run:") for p in source.files for line in _front_lines(p))


def _status_queued(source: Source, tracker: TrackerAdapter | None, run_id: str) -> None:
    if source.type == "github" and tracker is not None:
        tracker.set_status(source.ref, "factory:queued", comment=f"Run {run_id} is queued.")
    elif source.type == "markdown":
        for path in source.files:
            _set_front_matter(path, {"factory_status": "queued", "factory_run": run_id, "factory_error": None})


def _mark_invalid(source: Source, reason: str, tracker: TrackerAdapter, home: Path, key: str) -> None:
    """Tell the source why it was not picked up. Repeats are silent: a status already written is not written again."""
    if source.type == "github":
        if "factory:invalid" in source.labels:
            return
        tracker.set_status(source.ref, "factory:invalid", comment=f"Not picked up: {reason}")
    elif source.type == "markdown":
        if any(_has_error_key(p) for p in source.files):
            return
        for path in source.files:
            _set_front_matter(path, {"factory_error": json.dumps(reason)})
    else:
        return
    _record_event(home, key, "request_invalid", ref=source.ref, reason=reason)


def _has_error_key(path: Path) -> bool:
    return any(line.startswith("factory_error:") for line in _front_lines(path))


# --- dedupe and run ids ---

def _find_duplicate(home: Path, key: str, ref: str, body_sha: str) -> str | None:
    """The run id for the same source ref and body hash in the active runs or the archive, or None.

    history.jsonl records no source ref, so the archive is searched through each zipped run's request.json."""
    hit = state.find_by_source(home, key, ref, body_sha)
    if hit is not None:
        return hit
    archive = home / "archive" / key
    if not archive.is_dir():
        return None
    for zpath in sorted(archive.rglob("*.zip")):
        with zipfile.ZipFile(zpath) as z:
            names = [n for n in z.namelist() if n == "request.json" or n.endswith("/request.json")]
            if not names:
                continue
            req = json.loads(z.read(names[0]))
        if req.get("source", {}).get("ref") == ref and req.get("body_sha") == body_sha:
            return zpath.stem
    return None


def _active_runs_for_ref(home: Path, key: str, ref: str) -> list[Path]:
    out = []
    for rref in state.list_runs(home, key=key):
        run = state.read_run(rref.run_dir)
        if run.request.source.ref == ref and run.status not in TERMINAL:
            out.append(rref.run_dir)
    return out


def _ref_exists(repo: Path, ref: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", ref],
                          capture_output=True).returncode == 0


def _base_ref(repo: Path, cfg: Config) -> str:
    base = (cfg.repo or {}).get("base_branch", "main")
    return f"origin/{base}" if _ref_exists(repo, f"origin/{base}") else base


def _reserved_worktree(repo: Path, cfg: Config, run_id: str) -> Path:
    machine = cfg.machine or {}
    template = machine.get("worktree_path", "{root}/{repo}/{run_id}")
    root = Path(machine.get("worktree_root") or Path.home() / ".factory" / "worktrees")
    path = render(template, root=root, repo=repo.name, owner="", run_id=run_id, task=None)
    check_outside_repo(path, repo)
    return path


def _id_taken(home: Path, repo: Path, cfg: Config, rid: str) -> bool:
    """A run id is free only when no run folder, archive, branch or worktree path already uses it."""
    runs = home / "runs"
    if runs.is_dir() and any(p.is_dir() for p in runs.rglob(rid)):
        return True
    archive = home / "archive"
    if archive.is_dir() and any(archive.rglob(f"{rid}.zip")):
        return True
    for ref in (f"refs/heads/{rid}", f"refs/remotes/origin/{rid}"):
        if subprocess.run(["git", "-C", str(repo), "show-ref", "--verify", "--quiet", ref],
                          capture_output=True).returncode == 0:
            return True
    return _reserved_worktree(repo, cfg, rid).exists()


# --- creating runs ---

def _create(repo: Path, cfg: Config, request: Request, tracker: TrackerAdapter | None,
            home: Path, key: str) -> RunRef:
    request = replace(request, repo=repo.name)
    dup = _find_duplicate(home, key, request.source.ref, request.body_sha)
    if dup is not None:
        return RunRef(repo=repo, repo_key=key, run_id=dup, run_dir=state.run_dir(home, key, dup))
    run_id = state.new_run_id(request.title, exists=lambda rid: _id_taken(home, repo, cfg, rid))
    kit_hash = snapshot_kit(repo, _base_ref(repo, cfg), home)
    ref = state.init_run(home, repo, key, run_id, request, branch=None,
                         worktree=_reserved_worktree(repo, cfg, run_id), kit_hash=kit_hash)
    _status_queued(request.source, tracker, run_id)
    return ref


def create_run(repo: Path, cfg: Config, request: Request, tracker: TrackerAdapter) -> RunRef:
    """Dedupe (runs, archive) -> run id -> kit snapshot (7) -> state in the factory home (6A), with the worktree path
    reserved but not created (6B creates it when triage ends) -> status back to the source.

    A duplicate returns the existing run instead of a new one."""
    return _create(repo, cfg, request, tracker, state.factory_home(), state.repo_key(repo, cfg))


def _request_changed(run_dir: Path, body_sha: str) -> None:
    """Log the change and raise an attention item when the run is free. The run is never restarted here.

    When an engine holds the lock, the engine writes run state, so only the event is recorded now."""
    run = state.read_run(run_dir)
    if any(e.type == "request_changed" and e.data.get("body_sha") == body_sha for e in state.read_events(run_dir)):
        return  # this change was already logged on an earlier sync
    state.append_event(run_dir, "request_changed", body_sha=body_sha, previous_body_sha=run.request.body_sha)
    try:
        lock = state.acquire_lock(run_dir, owner="intake")
    except FactoryError as e:
        if e.code == "state.locked":
            return
        raise
    try:
        run = state.read_run(run_dir)
        if run.attention is None:
            run.attention = AttentionItem(
                kind="request_changed", run_id=run.run_id, stage=run.stage, since=_now(),
                summary="The request changed while this run was active. The run was not restarted.",
                page=None, command=None)
            state.write_run(run_dir, run, lock=lock)
    finally:
        state.release(lock)


def sync(repo: Path, cfg: Config, tracker: TrackerAdapter) -> SyncReport:
    """Read every source once and create a run for each new request. Invalid, duplicate and changed requests are
    reported in the result and handled as module 4 says."""
    home = state.factory_home()
    key = state.repo_key(repo, cfg)
    report = SyncReport()
    sources = read_sources(repo, cfg, tracker)
    github = sum(1 for source in sources if source.type == "github")
    if github >= SYNC_LIMIT:
        # gh stopped at the limit, so open issues beyond it were not read this sync (module 4, module 7).
        _record_event(home, key, "sync_limit_reached", limit=SYNC_LIMIT, returned=github,
                      message=f"{key}: the sync read {github} open factory issues, the limit of {SYNC_LIMIT}; "
                              f"issues beyond it are not read this sync")
    for source in sources:
        try:
            request = normalize(source, cfg)
        except FactoryError as e:
            if e.code != "intake.invalid":
                raise
            report.invalid.append(source.ref)
            _mark_invalid(source, e.message, tracker, home, key)
            continue
        dup = _find_duplicate(home, key, source.ref, request.body_sha)
        if dup is not None:
            report.duplicates.append(source.ref)
            if not _already_marked(source):
                # The run exists but the source was never marked (a crash between the two): finish the marking.
                _status_queued(source, tracker, dup)
                _record_event(home, key, "request_duplicate", ref=source.ref, run_id=dup)
            continue
        active = _active_runs_for_ref(home, key, source.ref)
        if active:
            for run_dir in active:
                _request_changed(run_dir, request.body_sha)
            report.changed.append(source.ref)
            continue
        report.created.append(_create(repo, cfg, request, tracker, home, key))
    return report


def add(repo: Path, cfg: Config, title: str, *, type: str | None = None,
        body: str | None = None, files: list[Path] | None = None) -> RunRef:
    """One submission from the CLI: the title, the body text and the files together form one run."""
    files = list(files or [])
    _, file_body, labels = _read_files(files) if files else ("", "", [])
    parts = [part.strip() for part in (body or "", file_body) if part and part.strip()]
    source = Source(type="cli", ref=f"cli-{secrets.token_hex(4)}", title=title, body="\n\n".join(parts),
                    labels=labels, author=None, files=files)
    request = normalize(source, cfg)
    if type is not None:
        if type not in TYPE_WORKFLOW:
            raise FactoryError("intake.invalid", f"unknown type {type!r}", hint=f"use one of {', '.join(TYPE_WORKFLOW)}")
        request = replace(request, type=type, type_source="explicit")
    return _create(repo, cfg, request, None, state.factory_home(), state.repo_key(repo, cfg))
