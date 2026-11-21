"""The pull request contract (module 7)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .types import PrRef, PrState


class PullRequests(Protocol):
    def create(self, worktree: Path, *, base: str, head: str, title: str, body_file: Path,
               labels: list[str]) -> PrRef: ...

    def state(self, pr: PrRef) -> PrState: ...

    def merge(self, pr: PrRef, *, method: str = "squash", auto: bool = True, delete_branch: bool = True) -> None: ...

    def request_reviewers(self, pr: PrRef, users: list[str]) -> None: ...

    def comment(self, pr: PrRef, body: str) -> None: ...
