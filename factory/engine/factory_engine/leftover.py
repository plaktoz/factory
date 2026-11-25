"""Ending a worker group a crashed engine left running (module 6, recovery; item 63).

A worker starts in its own session, so its process group id is its pid. A worker is launched after its attempt's
`started` record is written, so a group whose leader started before that record cannot be that worker. The leader's
start time is read from `ps` (macOS and Linux). The start time has one-second resolution, so a reused pid that started
in the same second as the record is not told apart; the guard is a check, not a proof.
"""

from __future__ import annotations

import os
import signal
import subprocess
from datetime import datetime


def _start_time(pid: int) -> datetime | None:
    """When the process started, in local time, or None when `ps` does not know the pid (it has exited)."""
    out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, check=False).stdout
    text = out.strip()
    if not text:
        return None
    return datetime.strptime(text, "%a %b %d %H:%M:%S %Y").astimezone()


def is_worker_group(pgid: int, attempt_started: datetime) -> bool:
    """True when the group leader `pgid` is alive and started no earlier than the attempt's record: then it is the
    worker that record announced. A pid that a later process took started after the record and is not this worker,
    but a pid that started before it cannot be the worker, so it is not signalled either."""
    if not _alive(pgid):
        return False
    started = _start_time(pgid)
    return started is not None and started >= attempt_started.replace(microsecond=0)


def _alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # the group exists but is not ours to signal: it is still a live group


def kill_group(pgid: int) -> None:
    """SIGKILL the whole group. A group that has already gone is not an error."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
