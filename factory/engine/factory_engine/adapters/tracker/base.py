"""The tracker contract (module 7)."""

from __future__ import annotations

from typing import Protocol

from ...types import Source


class TrackerAdapter(Protocol):
    def list_new(self, since: str | None) -> list[Source]: ...

    def fetch(self, ref: str) -> Source: ...

    def set_status(self, ref: str, status: str, *, comment: str | None = None, link: str | None = None) -> None: ...

    def ensure_labels(self, labels: list[str]) -> None: ...
