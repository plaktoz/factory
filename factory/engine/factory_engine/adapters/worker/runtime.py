"""What the worker adapters share (module 9): the minimal environment, build-cache folders, private per-attempt files.

Every attempt gets a folder under $FACTORY_HOME/tmp with mode 0700. Its files (sandbox settings, MCP config, the
prompt, captured output) are mode 0600, and the folder is removed when the attempt ends. Resolved secrets live only
in these files and in the child's environment, never in the run folder.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

from ...interpolate import resolve
from ...loadcfg import factory_home
from ...redact import mask
from ...types import McpServer

BASE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
# Declared variables that are not secrets. Everything else a harness declares is masked in logs.
NOT_SECRET = frozenset({"ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "FACTORY_TASK_DIR"})


def base_env(source: Mapping[str, str]) -> dict[str, str]:
    """The minimal base: PATH, HOME and the locale. Nothing else from the engine's environment passes through."""
    return {k: source[k] for k in BASE_ENV if source.get(k)}


def declared_env(env: Mapping[str, str]) -> dict[str, str]:
    """Declared variables with the empty ones dropped: an empty value counts as unset (module 9)."""
    return {k: v for k, v in env.items() if v != ""}


def cache_env(task_dir: Path) -> dict[str, str]:
    """Each tool's cache folder under this task's work folder, so the sandbox's write rule stays two paths (Q2)."""
    cache = task_dir / "cache"
    return {
        "npm_config_cache": str(cache / "npm"),
        "MAVEN_OPTS": f"-Dmaven.repo.local={cache / 'm2'}",
        "GOMODCACHE": str(cache / "go-mod"),
        "GOCACHE": str(cache / "go-build"),
        "PIP_CACHE_DIR": str(cache / "pip"),
    }


def secret_values(env: Mapping[str, str], mcp: list[McpServer]) -> list[str]:
    """Resolved values that must never reach a log: every declared value that is not a plain setting, and the
    resolved MCP headers and environment."""
    values = [v for k, v in env.items() if k not in NOT_SECRET and v]
    for s in mcp:
        values += [v for v in list(s.headers.values()) + list(s.env.values()) if v]
    return values


def resolve_mcp(servers: list[McpServer], env: Mapping[str, str]) -> list[McpServer]:
    """Resolve ${...} in MCP headers and environment when the attempt starts (module 9, per-attempt config)."""
    out = []
    for s in servers:
        headers = {k: resolve(v, env, where=f"mcp {s.name} header {k}") for k, v in s.headers.items()}
        menv = {k: resolve(v, env, where=f"mcp {s.name} env {k}") for k, v in s.env.items()}
        out.append(McpServer(s.name, s.url, list(s.command) if s.command else None, headers, menv))
    return out


def attempt_folder(label: str) -> Path:
    root = factory_home() / "tmp"
    root.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix=f"{label}-", dir=root))
    os.chmod(d, 0o700)
    return d


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def remove_attempt(folder: Path | None) -> None:
    if folder is not None:
        shutil.rmtree(folder, ignore_errors=True)


def write_log(path: Path, text: str, secrets: list[str]) -> None:
    """worker.log is raw text (module 6). Resolved secrets are masked before the file is written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mask(text, secrets))


def read_text(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return path.read_text(errors="replace")
