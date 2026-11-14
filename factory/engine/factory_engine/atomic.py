"""Atomic writes and tolerant .jsonl reads (module 6A state file rules)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, doc: Any) -> None:
    """Write through a temporary file in the same folder, fsync, then rename. A reader sees the old file or the
    new one, never half of either. A crash leaves at most a stray temp file, which is removed on the next write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(doc, indent=2, sort_keys=False) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append_jsonl(path: Path, line: dict) -> None:
    """One line per write. The line is written in one call so two appenders cannot interleave inside it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(line, separators=(",", ":")) + "\n").encode()
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def read_jsonl(path: Path) -> list[dict]:
    """Every whole line. A cut-off last line (no newline, or not JSON) is ignored, never an error."""
    if not path.is_file():
        return []
    out: list[dict] = []
    raw = path.read_bytes()
    lines = raw.split(b"\n")
    complete = lines[:-1] if raw.endswith(b"\n") else lines[:-1]  # the last piece has no newline: it may be cut off
    for chunk in complete:
        if not chunk.strip():
            continue
        try:
            out.append(json.loads(chunk))
        except json.JSONDecodeError:
            continue
    return out
