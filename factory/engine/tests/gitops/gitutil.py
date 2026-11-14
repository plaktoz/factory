"""Helpers for module 7 tests: run git on a temp repo, and list the remote's refs."""

import subprocess
from pathlib import Path

GIT_ID = ["-c", "user.name=test", "-c", "user.email=test@example.invalid"]


def run(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *GIT_ID, "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return r.stdout.strip()


def ls_remote(repo: Path) -> list[str]:
    out = run(repo, "ls-remote", "origin")
    return [line.split("\t")[1] for line in out.splitlines() if line]
