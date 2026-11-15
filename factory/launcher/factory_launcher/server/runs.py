"""Finds the run folders under runs/ and reads them with the 6A functions (module 15).

RunScanner is not used. Its scan() parses every run.json on every call (through list_runs), and one unreadable file
fails the whole scan. This index compares each run.json's mtime and size, and reads with read_run only the files that
changed. A file that cannot be read becomes an entry with an error, so one bad folder never breaks the page.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from factory_engine.errors import FactoryError
from factory_engine.state import read_run
from factory_engine.types import Run


@dataclass
class Entry:
    run_dir: Path
    repo_key: str
    run_id: str
    updated: datetime  # run.json's modification time, local time
    run: Run | None = None
    error: str | None = None


def _mtime(st) -> datetime:
    return datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).astimezone()


def _read(run_dir: Path, repo_key: str, updated: datetime) -> Entry:
    try:
        return Entry(run_dir, repo_key, run_dir.name, updated, run=read_run(run_dir))
    except Exception as e:  # noqa: BLE001 - one unreadable folder is shown as a row, never a crash
        message = e.message if isinstance(e, FactoryError) else f"{type(e).__name__}: {e}"
        return Entry(run_dir, repo_key, run_dir.name, updated, error=message)


class RunIndex:
    """The runs in the factory home. scan() is called on every refresh and reads only changed run.json files."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self._lock = threading.Lock()
        self._seen: dict[Path, tuple[tuple[int, int], Entry]] = {}

    def scan(self) -> list[Entry]:
        with self._lock:
            runs = self.home / "runs"
            seen: dict[Path, tuple[tuple[int, int], Entry]] = {}
            for run_json in sorted(runs.rglob("run.json")) if runs.is_dir() else []:
                run_dir = run_json.parent
                try:
                    st = run_json.stat()
                    repo_key = str(run_dir.parent.relative_to(runs))  # a repo key may hold slashes
                except (OSError, ValueError):
                    continue  # vanished mid-scan, or not under runs/<repo key>/<run id>
                sig = (st.st_mtime_ns, st.st_size)
                old = self._seen.get(run_dir)
                if old is not None and old[0] == sig:
                    seen[run_dir] = old
                else:
                    seen[run_dir] = (sig, _read(run_dir, repo_key, _mtime(st)))
            self._seen = seen
            return [entry for _, entry in seen.values()]

    def get(self, run_id: str) -> Entry | None:
        for entry in self.scan():
            if entry.run_id == run_id:
                return entry
        return None
