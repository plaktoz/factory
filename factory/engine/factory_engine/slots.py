"""Worker slots (module 3, `max_workers` and `concurrency`): one lock file for each slot in a pool folder.

Each engine process takes slots before it starts a worker, and holds them until that worker has ended. The machine pool
is `slots/` under the factory home, sized by `max_workers`; each repo has its own pool, sized by `concurrency`, so two
runs of one repo share that cap. A slot is a kernel lock (`filelock`), so a crashed engine frees its slots when its file
descriptors close, and no count can go stale. The tick starts one engine process for each run, so the count lives in
the file system, not in one process.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import filelock


def machine_pool(home: Path) -> Path:
    return home / "slots"


def repo_pool(home: Path, repo_key: str) -> Path:
    return home / "slots" / "repo" / repo_key.replace("/", "__")


def acquire(pool: Path, limit: int, count: int) -> list[int] | None:
    """Take `count` free slots out of `limit` in `pool`, all at once or none, without waiting. Returns the file
    descriptors that hold them, or None when fewer than `count` are free. The caller gives them back with `release_all`."""
    pool.mkdir(parents=True, exist_ok=True)
    held: list[int] = []
    for i in range(limit):
        if len(held) == count:
            break
        fd = os.open(str(pool / str(i)), os.O_RDWR | os.O_CREAT, 0o644)
        if filelock.try_lock(fd):
            held.append(fd)
        else:
            os.close(fd)
    if len(held) < count:
        release_all(held)
        return None
    return held


def release(fd: int) -> None:
    """Give back one slot: unlock it, then close the file."""
    filelock.unlock(fd)
    os.close(fd)


def release_all(fds: list[int]) -> None:
    for fd in fds:
        release(fd)
