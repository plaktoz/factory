"""FakeTracker: an in-memory tracker for other modules' tests (module 7).

Items are added with add(). list_new(since) returns items added after the cursor `since` (the cursor is the
position in the order items were added, as a string; None means from the start), and fails when fail_next
holds an error. Every set_status call is recorded, so a test can assert what the factory told the source.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...types import Source


@dataclass
class StatusCall:
    ref: str
    status: str
    comment: str | None
    link: str | None


class FakeTracker:
    def __init__(self, items: list[Source] | None = None):
        self.items: list[Source] = list(items or [])
        self.statuses: list[StatusCall] = []
        self.labels: set[str] = set()
        self.fail_next: Exception | None = None  # raised once by the next call, then cleared
        self.calls: list[str] = []

    def add(self, source: Source) -> None:
        self.items.append(source)

    def cursor(self) -> str:
        """The cursor after the items added so far; pass it back as `since` to see only later items."""
        return str(len(self.items))

    def _maybe_fail(self) -> None:
        if self.fail_next is not None:
            err, self.fail_next = self.fail_next, None
            raise err

    def list_new(self, since: str | None) -> list[Source]:
        self.calls.append("list_new")
        self._maybe_fail()
        start = int(since) if since else 0
        return list(self.items[start:])

    def fetch(self, ref: str) -> Source:
        self.calls.append("fetch")
        self._maybe_fail()
        for s in self.items:
            if s.ref == ref:
                return s
        raise KeyError(f"no item {ref!r}")

    def set_status(self, ref: str, status: str, *, comment: str | None = None, link: str | None = None) -> None:
        self.calls.append("set_status")
        self._maybe_fail()
        self.statuses.append(StatusCall(ref, status, comment, link))

    def ensure_labels(self, labels: list[str]) -> None:
        self.calls.append("ensure_labels")
        self._maybe_fail()
        self.labels.update(labels)

    def last_status(self, ref: str) -> str | None:
        for c in reversed(self.statuses):
            if c.ref == ref:
                return c.status
        return None
