"""The sandbox rules shared by workers and commands (module 9).

One rule set serves both. The factory home and the harness credential folders are unreadable. This task's `work/`
folder and its worktree are readable. Writes reach only the worktree and `work/`. Claude workers get these rules as a
per-attempt settings file (claude.py). Deterministic tasks get them as an `srt` settings file (this module).
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from ...errors import CATALOGUE, FactoryError
from ...loadcfg import factory_home
from ...types import CheckResult

SRT_VERSION = "0.0.83"
NODE_FLOOR = (22, 12)
# Credential folders that no worker reads. The Claude entries are the harness's own config and state.
CREDENTIAL_PATHS = ("~/.ssh", "~/.aws", "~/.config/gh", "~/.claude", "~/.claude.json")


def _resolved(p: str | Path) -> Path:
    return Path(p).expanduser().resolve()


def deny_read(factory: Path | None = None) -> list[str]:
    home = factory if factory is not None else factory_home()
    return [str(_resolved(home))] + [str(_resolved(p)) for p in CREDENTIAL_PATHS]


def allow_read(worktree: Path, task_dir: Path) -> list[str]:
    # The worktree sits under the factory home by default, so it must be listed to stay readable.
    return [str(_resolved(task_dir)), str(_resolved(worktree))]


def allow_write(worktree: Path, task_dir: Path) -> list[str]:
    return [str(_resolved(worktree)), str(_resolved(task_dir))]


def filesystem(worktree: Path, task_dir: Path, factory: Path | None = None) -> dict:
    return {"denyRead": deny_read(factory), "allowRead": allow_read(worktree, task_dir),
            "allowWrite": allow_write(worktree, task_dir), "denyWrite": []}


def srt_settings(worktree: Path, task_dir: Path, factory: Path | None = None) -> dict:
    """The settings `srt` reads. It needs `denyWrite` and `deniedDomains` present, or it refuses to run (2026-11-14)."""
    return {"filesystem": filesystem(worktree, task_dir, factory),
            "network": {"allowedDomains": [], "deniedDomains": []}}


def srt_bin() -> str | None:
    return shutil.which("srt")


def node_version() -> tuple[int, int, int] | None:
    node = shutil.which("node")
    if node is None:
        return None
    out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout
    m = re.search(r"v?(\d+)\.(\d+)\.(\d+)", out)
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def check_srt() -> CheckResult:
    """Doctor's check for the command sandbox: srt is installed at the pinned version and Node is new enough."""
    if srt_bin() is None:
        return CheckResult("srt", False, f"sandbox.srt_missing: srt is not on PATH",
                           f"npm install -g @anthropic-ai/sandbox-runtime@{SRT_VERSION}")
    node = node_version()
    if node is None or node[:2] < NODE_FLOOR:
        found = "not installed" if node is None else ".".join(map(str, node))
        return CheckResult("srt", False, f"sandbox.node_old: Node {found}, srt needs {NODE_FLOOR[0]}.{NODE_FLOOR[1]} or later",
                           CATALOGUE["sandbox.node_old"].hint)
    return CheckResult("srt", True, f"srt on PATH; Node {'.'.join(map(str, node))}", "")


def require_srt() -> str:
    """The srt binary path, or a fail_fast sandbox error. A command never runs unsandboxed when srt is missing."""
    bin_ = srt_bin()
    if bin_ is None:
        raise FactoryError("sandbox.srt_missing", "srt is not on PATH; commands would run unsandboxed",
                           hint=f"npm install -g @anthropic-ai/sandbox-runtime@{SRT_VERSION}")
    node = node_version()
    if node is None or node[:2] < NODE_FLOOR:
        raise FactoryError("sandbox.node_old", f"Node {node or 'missing'} is older than {NODE_FLOOR[0]}.{NODE_FLOOR[1]}")
    return bin_


def srt_command(bin_: str, settings: Path, argv: list[str]) -> list[str]:
    """`srt -c` takes one shell string, so each element is quoted. Elements stay single arguments (module 9)."""
    return [bin_, "-s", str(settings), "-c", " ".join(shlex.quote(a) for a in argv)]


def canary_srt(worktree: Path, task_dir: Path, factory: Path | None = None) -> CheckResult:
    """Doctor's canary for srt: plant a file outside the worktree and try each route. Reads must fail; the two writes
    inside the worktree and the task folder must work; a write outside both must fail. Any open route fails the check
    and names the route."""
    bin_ = require_srt()
    home = factory if factory is not None else factory_home()
    scratch = home / "tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    canary = scratch / "canary-secret.txt"
    canary.write_text("canary\n")
    outside = scratch / "canary-outside.txt"
    settings_path = scratch / "canary-srt-settings.json"
    settings_path.write_text(json.dumps(srt_settings(worktree, task_dir, home)))
    routes = {
        "read via cat": (["cat", str(canary)], False),
        "read via python": (["python3", "-c", f"open({str(canary)!r}).read()"], False),
        "write in worktree": (["sh", "-c", f"echo ok > {shlex.quote(str(worktree / 'canary-in-worktree.txt'))}"], True),
        "write in task folder": (["sh", "-c", f"echo ok > {shlex.quote(str(task_dir / 'canary-in-work.txt'))}"], True),
        "write outside both": (["sh", "-c", f"echo ok > {shlex.quote(str(outside))}"], False),
    }
    open_routes = []
    try:
        for name, (argv, should_pass) in routes.items():
            r = subprocess.run(srt_command(bin_, settings_path, argv), cwd=worktree, capture_output=True, text=True)
            passed = r.returncode == 0
            if passed != should_pass:
                open_routes.append(name)
    finally:
        for p in (canary, outside, settings_path, worktree / "canary-in-worktree.txt", task_dir / "canary-in-work.txt"):
            p.unlink(missing_ok=True)
    if open_routes:
        return CheckResult("srt canary", False, "sandbox.canary_open: " + ", ".join(open_routes), CATALOGUE["sandbox.canary_open"].hint)
    return CheckResult("srt canary", True, "every route as the settings say", "")
