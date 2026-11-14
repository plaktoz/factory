"""SystemClock and FakeClock, both implementing the Clock protocol of section 18 (G5)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc).astimezone()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class FakeClock:
    """A clock a test moves by hand. sleep() advances time and returns at once, so a test never waits."""

    def __init__(self, start: datetime | None = None):
        self._now = start or datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self._now

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("sleep takes a non-negative number of seconds")
        self.sleeps.append(seconds)
        self._now += timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
