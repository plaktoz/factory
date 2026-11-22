"""Non-blocking OS file lock for the run lock and the tick lock (module 6A, phase 2 item P2-2, issue #103).

POSIX uses `fcntl.flock`, which locks the whole file. Windows uses `msvcrt.locking` on one byte at a fixed offset
past the heartbeat JSON. That byte-range lock is mandatory, so it would block a reader of the locked bytes; the
heartbeat is written at offset 0 and the JSON is far shorter than the offset, so readers never touch the locked byte.

Both kinds of lock are released by the kernel when the process exits, so a crashed holder frees them at once.
"""

from __future__ import annotations

import os
import sys

if sys.platform == "win32":
    import msvcrt

    # Past any heartbeat JSON (a few hundred bytes at most). Locking beyond end of file is allowed on Windows.
    LOCK_OFFSET = 1 << 20

    def try_lock(fd: int) -> bool:
        """Take the lock without waiting. False when another process or handle holds it."""
        os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def unlock(fd: int) -> None:
        os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def try_lock(fd: int) -> bool:
        """Take the lock without waiting. False when another process holds it."""
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
