"""Temp repos, factory homes and run folders for module 17 tests. Git runs for real, on temp repos with no remote."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gitops"))
from gitutil import run as git_run  # noqa: E402

from factory_engine.clock import FakeClock  # noqa: E402
from factory_engine.config import Config  # noqa: E402


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def wt_root(tmp_path):
    w = tmp_path / "wt"
    w.mkdir()
    return w


@pytest.fixture
def repo(tmp_path):
    src = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    (src / "app.py").write_text("x = 1\n")
    git_run(src, "add", "-A")
    git_run(src, "commit", "-q", "-m", "init")
    return src


@pytest.fixture
def cfg(wt_root):
    return Config(machine={"worktree_root": str(wt_root)}, repo=None)














