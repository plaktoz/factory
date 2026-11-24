"""Live view and steering (module 12): notes queued for a running task, and the log tail.

`tasks/<task>/notes.jsonl` is append-only. A `queued` line holds the note, and a later `delivered` line with the same
id marks it delivered. The last line for an id wins. Restarting the worker is module 6B's job, and applying a note's
deny paths to the task is 6B's job too, so this module only stores and reports them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .atomic import append_jsonl, read_jsonl
from .errors import FactoryError
from .state import append_event, read_task, task_dir

SCHEMA_VERSION = 1
FINISHED = ("done", "failed")
_BLOCK = 8192


@dataclass
class NoteRef:
    task_id: str
    note_id: int


@dataclass
class Note:
    id: int
    text: str
    deny: list[str]
    by: str
    queued_at: str
    delivered_attempt: int | None = None
    delivered_at: str | None = None


def _path(run_dir: Path, task_id: str) -> Path:
    return task_dir(run_dir, task_id) / "notes.jsonl"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _all(run_dir: Path, task_id: str) -> list[Note]:
    notes: dict[int, Note] = {}
    for line in read_jsonl(_path(run_dir, task_id)):
        if line["state"] == "queued":
            notes[line["id"]] = Note(line["id"], line["text"], list(line["deny"]), line["by"], line["ts"])
        elif line["id"] in notes:
            notes[line["id"]].delivered_attempt = line["attempt"]
            notes[line["id"]].delivered_at = line["ts"]
    return sorted(notes.values(), key=lambda n: n.id)


def queue_note(run_dir: Path, task_id: str, text: str, *, deny: list[str] | None = None, by: str) -> NoteRef:
    """Append a queued note. A finished task refuses it, and a task the run does not have is a config error."""
    if not (task_dir(run_dir, task_id) / "task.json").is_file():
        raise FactoryError("config.invalid", f"run has no task {task_id!r}", hint="factory events <run> lists what ran")
    status = read_task(run_dir, task_id).status
    if status in FINISHED:
        raise FactoryError("notes.task_finished", f"task {task_id} is {status}, so it cannot take a note",
                           hint="notes steer a running task; open a rework or a new request instead")
    note_id = 1 + max((n.id for n in _all(run_dir, task_id)), default=0)
    append_jsonl(_path(run_dir, task_id), {"schema_version": SCHEMA_VERSION, "state": "queued", "id": note_id, "text": text,
                                           "deny": list(deny or []), "by": by, "ts": _now()})
    append_event(run_dir, "note_queued", task_id=task_id, note_id=note_id, by=by, deny=list(deny or []))
    return NoteRef(task_id, note_id)


def pending_notes(run_dir: Path, task_id: str) -> list[Note]:
    return [n for n in _all(run_dir, task_id) if n.delivered_attempt is None]


def mark_delivered(run_dir: Path, task_id: str, note_ids: list[int], *, attempt: int) -> None:
    """Mark notes delivered to `attempt`. A note already delivered is left as it is, so a repeat call changes nothing."""
    notes = {n.id: n for n in _all(run_dir, task_id)}
    unknown = [i for i in note_ids if i not in notes]
    if unknown:
        raise FactoryError("config.invalid", f"task {task_id} has no note {unknown}", hint="list the pending notes first")
    for i in note_ids:
        if notes[i].delivered_attempt is not None:
            continue
        append_jsonl(_path(run_dir, task_id), {"schema_version": SCHEMA_VERSION, "state": "delivered", "id": i,
                                               "attempt": attempt, "ts": _now()})
        append_event(run_dir, "note_delivered", task_id=task_id, note_id=i, attempt=attempt)


def delivered_notes(run_dir: Path, task_id: str) -> list[str]:
    """The text of every delivered note, oldest first, for the prompt."""
    return [n.text for n in _all(run_dir, task_id) if n.delivered_attempt is not None]


def delivered_deny(run_dir: Path, task_id: str) -> list[str]:
    """The deny paths of every note that has been delivered to the task. 6B adds them to the task's scope check."""
    return [d for n in _all(run_dir, task_id) if n.delivered_attempt is not None for d in n.deny]


def tail_log(path: Path, lines: int = 200) -> str:
    """The last `lines` lines of a file, read backwards in blocks so a large log is never loaded whole.
    A missing file gives an empty string. Bytes that are not UTF-8 are replaced, so the raw output is kept."""
    if lines <= 0 or not path.is_file():
        return ""
    with path.open("rb") as f:
        pos = f.seek(0, 2)
        data = b""
        while pos > 0 and data.count(b"\n") <= lines:
            step = min(_BLOCK, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step) + data
    out = data.decode("utf-8", errors="replace").split("\n")
    if out and out[-1] == "":
        out.pop()
    out = out[-lines:]
    return "\n".join(out) + ("\n" if out else "")
