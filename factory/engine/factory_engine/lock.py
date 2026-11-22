"""The run lock (module 6A, decision D1): an OS file lock held for the life of the owning process.

The lock is a kernel lock (`filelock`: fcntl.flock on POSIX, msvcrt.locking on Windows), so a crash releases it at
once, and a process that is stopped (SIGSTOP) keeps it. Heartbeat is display only (module 6A): it never decides
ownership, so `acquire_lock` refuses while the holder lives, whatever its heartbeat says.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from . import filelock
from .atomic import write_json_atomic
from .errors import FactoryError


@dataclass
class Lock:
    path: Path
    fd: int
    owner: str
    pid: int


def acquire_lock(run_dir: Path, owner: str) -> Lock:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "lock"
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    if not filelock.try_lock(fd):
        os.close(fd)
        holder = _read_holder(path)
        raise FactoryError("state.locked", f"run {run_dir.name} is locked by {holder.get('owner', 'another engine')} "
                           f"(pid {holder.get('pid', '?')})",
                           hint="wait for that engine to finish, or stop it; then retry") from None
    lock = Lock(path, fd, owner, os.getpid())
    heartbeat(lock)
    return lock


def _read_holder(path: Path) -> dict:
    try:
        return json.loads(path.read_text() or "{}")
    except (OSError, json.JSONDecodeError):
        return {}


def heartbeat(lock: Lock) -> None:
    """Display only: records pid, owner and the time. Nothing decides ownership from it."""
    os.ftruncate(lock.fd, 0)
    data = json.dumps({"owner": lock.owner, "pid": lock.pid, "heartbeat": time.time()}).encode()
    os.lseek(lock.fd, 0, 0)
    os.write(lock.fd, data)


def release(lock: Lock) -> None:
    """Idempotent: a second call, or a call on a lock whose fd is already closed, does nothing."""
    if lock.fd < 0:
        return
    fd, lock.fd = lock.fd, -1
    try:
        filelock.unlock(fd)
    except OSError:
        pass  # already unlocked or closed; the close below still runs
    finally:
        os.close(fd)


def _run_status(run_dir: Path) -> str | None:
    try:
        return json.loads((run_dir / "run.json").read_text()).get("status")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def lock_status(run_dir: Path) -> str:
    """live: the lock is held by a process. free: not held. stale: not held while run.json says running.

    The probe takes the lock and releases it at once, so it never blocks a real holder. The run's status is read
    from run.json, so the signature is the spec's (module 6A)."""
    run_status = _run_status(run_dir)
    path = run_dir / "lock"
    if not path.is_file():
        return "stale" if run_status == "running" else "free"
    fd = os.open(str(path), os.O_RDWR)
    try:
        if not filelock.try_lock(fd):
            return "live"
        filelock.unlock(fd)
        return "stale" if run_status == "running" else "free"
    finally:
        os.close(fd)
