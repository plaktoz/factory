"""Errors, error kinds, the error-code catalogue and CLI exit codes (section 18 and 19)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ErrorKind = Literal["fail_fast", "transient", "task_retry", "rework", "human"]
ERROR_KINDS: tuple[ErrorKind, ...] = ("fail_fast", "transient", "task_retry", "rework", "human")

# CLI exit codes, shared by all commands.
EXIT_OK = 0             # success, or the run is done
EXIT_FAILED = 1         # failed or unexpected error
EXIT_INVALID = 2        # invalid input or config (fail_fast)
EXIT_WAITING_HUMAN = 3  # waiting on a human
EXIT_BLOCKED = 4        # run blocked
EXIT_LOCKED = 5         # run locked by another engine


@dataclass(frozen=True)
class CatalogueEntry:
    kind: ErrorKind
    hint: str


# Every FactoryError.code is listed here. A module adds its rows in the wave that builds it.
CATALOGUE: dict[str, CatalogueEntry] = {
    "config.invalid": CatalogueEntry("fail_fast", "Name the file, the line and the form to write"),
    "config.no_credentials": CatalogueEntry(
        "fail_fast",
        "Set ANTHROPIC_API_KEY, or ANTHROPIC_AUTH_TOKEN with ANTHROPIC_BASE_URL; "
        "a login session is not supported in phase 1",
    ),
    "state.locked": CatalogueEntry("fail_fast", "Another engine holds the run; exit 5"),
    "git.hook_failed": CatalogueEntry("human", "Show the hook output"),
    "notes.task_finished": CatalogueEntry("fail_fast", "A note for a finished task is refused"),
    "sandbox.unavailable": CatalogueEntry(
        "human", "The OS refused to start the sandbox (sandbox_apply: Operation not permitted, exit 71)"
    ),
    "sandbox.settings_invalid": CatalogueEntry(
        "fail_fast", "The settings file parses but a field fails validation; name the field"
    ),
    "sandbox.settings_unreadable": CatalogueEntry(
        "fail_fast", "The --settings file is missing or unreadable; name the path"
    ),
    "sandbox.settings_unparseable": CatalogueEntry(
        "fail_fast",
        "The settings file is not JSON; Claude runs with no sandbox on such a file, "
        "so the adapter parses it before the worker starts",
    ),
    "sandbox.srt_missing": CatalogueEntry("fail_fast", "srt is not installed; give the install command"),
    "sandbox.node_old": CatalogueEntry("fail_fast", "Node is older than 22.12, which srt needs"),
    "skills.unknown": CatalogueEntry("fail_fast", "No override, locked skill or own skill matches the name; add one"),
    "git.network": CatalogueEntry("transient", "A GitHub or network call failed on a rate limit, a timeout or a lost connection; retry with backoff"),
    "git.index_locked": CatalogueEntry("transient", "index.lock is held by another git process; retry"),
    "git.push_rejected": CatalogueEntry("human", "The push was rejected after one base sync and one retry; show the rejection"),
    "git.auth_expired": CatalogueEntry("human", "GitHub login has expired; run gh auth login"),
    "git.command_failed": CatalogueEntry("task_retry", "A git command failed and matches no other git code; the message holds git's stderr"),
    "git.path_exists": CatalogueEntry("fail_fast", "A worktree or branch path already exists; name the path"),
    "git.worktree_dirty": CatalogueEntry("human", "A worktree with changes was not removed; show the files"),
    "sandbox.canary_open": CatalogueEntry(
        "human", "doctor found a read or write route that is not blocked; name the route"
    ),
}

_EXIT_BY_KIND: dict[ErrorKind, int] = {
    "fail_fast": EXIT_INVALID,
    "transient": EXIT_FAILED,
    "task_retry": EXIT_FAILED,
    "rework": EXIT_FAILED,
    "human": EXIT_WAITING_HUMAN,
}


class FactoryError(Exception):
    """A failure with a namespaced code, what happened, what to do, and how it is handled.

    The kind and hint default to the catalogue entry, so a module raises with a code and a message.
    A code that is not in the catalogue is a programming error and raises ValueError.
    """

    def __init__(self, code: str, message: str, *, hint: str | None = None, kind: ErrorKind | None = None):
        entry = CATALOGUE.get(code)
        if entry is None:
            raise ValueError(f"error code {code!r} is not in the catalogue (errors.CATALOGUE)")
        if kind is not None and kind not in ERROR_KINDS:
            raise ValueError(f"unknown error kind {kind!r}")
        self.code = code
        self.message = message
        self.hint = hint if hint is not None else entry.hint
        self.kind: ErrorKind = kind if kind is not None else entry.kind
        super().__init__(f"{code}: {message}")

    @property
    def exit_code(self) -> int:
        if self.code == "state.locked":
            return EXIT_LOCKED
        return _EXIT_BY_KIND[self.kind]

    def to_json(self) -> dict:
        """The shared --json error shape."""
        return {"ok": False, "code": self.code, "message": self.message, "hint": self.hint, "data": {}}
