"""Writes go through the launcher (module 15): `factory <command> ... --json`, run as a separate process so each repo's
own engine version applies the change. The dashboard never writes run state itself."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LauncherResult:
    doc: dict | None  # the CLI's JSON document, when it printed one
    returncode: int | None
    stderr: str


# The server passes the whole argument list, `--json` included, and the runner runs it with `factory` in front.
Launcher = Callable[[list[str]], LauncherResult]


class SubprocessLauncher:
    """Runs `<executable> <args>` with FACTORY_HOME set to the dashboard's home."""

    def __init__(self, *, home: Path, executable: str = "factory", timeout: float = 120.0) -> None:
        self.home = home
        self.executable = executable
        self.timeout = timeout

    def __call__(self, args: list[str]) -> LauncherResult:
        env = {**os.environ, "FACTORY_HOME": str(self.home)}
        try:
            proc = subprocess.run([self.executable, *args], capture_output=True, text=True,
                                  timeout=self.timeout, env=env, check=False)
        except OSError as e:
            return LauncherResult(None, None, f"could not start {self.executable}: {e}")
        except subprocess.TimeoutExpired:
            return LauncherResult(None, None, f"{self.executable} did not finish within {self.timeout:g} s")
        try:
            doc = json.loads(proc.stdout)
        except ValueError:
            doc = None
        return LauncherResult(doc if isinstance(doc, dict) else None, proc.returncode, proc.stderr.strip())
