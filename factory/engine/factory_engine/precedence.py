"""Precedence (module 3): flag > env var > file > default. The file is the machine file for machine keys and
the repo file for repo keys. Pure functions; the caller passes the values it has."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_MISSING = object()


def pick(key: str, *, flags: Mapping[str, Any], env: Mapping[str, str], env_name: str | None,
         file: Mapping[str, Any], default: Any = None) -> Any:
    if key in flags and flags[key] is not None:
        return flags[key]
    if env_name and env.get(env_name):
        return env[env_name]
    if key in file and file[key] is not None:
        return file[key]
    return default
