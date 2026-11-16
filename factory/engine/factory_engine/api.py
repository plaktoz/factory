"""The repo engine's driver functions (module 16): one function per command, each composing modules.

Only drivers compose modules and only drivers may import `engine.py`. The blocked-run actions of module 8 (retry,
goto, skip) change a run and start no worker, so they build an Engine with no worker adapter. `spawn_engine` is the
one function that starts work.
"""

from __future__ import annotations

from pathlib import Path

from .engine import Engine
from .loadcfg import load_config


def _engine(repo: Path) -> Engine:
    return Engine(repo, load_config(repo), workers={}, tracker=None, prs=None, owner="cli")


def retry(repo, run_id, *, stage=None, note=None) -> None:
    """Run a blocked stage once more, with the note queued as feedback. Loop counters are unchanged."""
    _engine(repo).retry(run_id, stage=stage, note=note)


def goto(repo, run_id, stage) -> None:
    """Send a blocked run back to this stage or an earlier one. The stage and every later stage start again."""
    _engine(repo).goto(run_id, stage)


def skip(repo, run_id, gate, *, reason) -> None:
    """Pass a gate the workflow marks `skippable: true`. Logs the skip and stops auto-merge."""
    _engine(repo).skip(run_id, gate, reason=reason)
