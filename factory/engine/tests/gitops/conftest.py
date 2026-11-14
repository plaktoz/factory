"""Temp repos for module 7 tests. Each test gets a repo with a local bare remote (module 7: 'a local bare remote')."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_engine.config import Config  # noqa: E402
from gitutil import run  # noqa: E402


@pytest.fixture
def repo(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    src = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    (src / "services").mkdir()
    (src / "services" / "api.py").write_text("x = 1\n")
    (src / "web").mkdir()
    (src / "web" / "app.js").write_text("y = 1\n")
    run(src, "add", "-A")
    run(src, "commit", "-q", "-m", "init")
    run(src, "remote", "add", "origin", str(bare))
    run(src, "push", "-q", "origin", "main")
    return src


@pytest.fixture
def cfg(tmp_path):
    return Config(machine={"worktree_root": str(tmp_path / "wt"),
                           "worktree_path": "{root}/{repo}/{run_id}"}, repo={"base_branch": "main"})


