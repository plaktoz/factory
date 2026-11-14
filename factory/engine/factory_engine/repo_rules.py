"""Rules on the repo file that the spec states in module 3 and module 9.

- A literal value under `env` in .factory/config/ is refused (module 3, module 9): a secret is `${...}`.
- `cleanup_check` is a list of strings, never a shell string (module 3, Q3).
"""

from __future__ import annotations

from collections.abc import Mapping

from .errors import FactoryError
from .interpolate import is_reference


def refuse_literal_env(harness_env: Mapping[str, str], *, file: str) -> None:
    for name, value in harness_env.items():
        if not is_reference(str(value)):
            raise FactoryError("config.invalid", f"{file}: env.{name} is a literal value, not a ${{...}} reference",
                               hint=f"move the secret to ~/.factory/env and write ${{{name}}} here")


def check_cleanup_check(value, *, file: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        raise FactoryError("config.invalid", f"{file}: cleanup_check is a string; it must be a list of strings",
                           hint='write it as a list, for example cleanup_check: ["scripts/compare-worktree"]')
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise FactoryError("config.invalid", f"{file}: cleanup_check must be a list of strings",
                           hint='write it as a list, for example cleanup_check: ["scripts/compare-worktree"]')
    if not value:
        raise FactoryError("config.invalid", f"{file}: cleanup_check is an empty list",
                           hint="remove the key, or give the command as a list")
    return list(value)
