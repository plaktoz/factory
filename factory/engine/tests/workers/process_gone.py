"""Waits for a process to be gone, for tests that check a process stopped (module 9).

A process that has just been killed can still answer `os.kill(pid, 0)` until its parent reaps it, so a single check
right after the kill fails at random under load. This polls for a short time instead. It is a plain module, not a
conftest: a `from conftest import ...` resolves to another folder's conftest in a full run.
"""

import os
import time


def gone_within(pid: int, seconds: float = 5.0) -> bool:
    """True when no process with this PID exists within `seconds`."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)
