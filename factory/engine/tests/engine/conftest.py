"""Fixtures for the module 6B tests: a real git repo, a factory home, and an Engine wired to the fakes."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from factory_engine import gitops, skills, state
from factory_engine.adapters.tracker.fake import FakeTracker
from factory_engine.adapters.worker.fake import FakeWorkerAdapter
from factory_engine.clock import FakeClock
from factory_engine.config import Config
from factory_engine.engine import Engine
from factory_engine.fake_prs import FakePullRequests
from factory_engine.types import Request, Source

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gitops"))
from gitutil import run as git  # noqa: E402

KIT = Path(__file__).resolve().parents[3]  # factory/


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    skills.use_kit(KIT)
    yield
    skills.use_kit(Path(skills.__file__).resolve().parents[2])


@pytest.fixture
def repo(tmp_path) -> Path:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    src = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    (src / "services").mkdir()
    (src / "services" / "api.py").write_text("x = 1\n")
    shutil.copytree(KIT, src / "factory", ignore=shutil.ignore_patterns(".venv", "__pycache__", "tests", "engine", "dashboard"))
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "init")
    git(src, "remote", "add", "origin", str(bare))
    git(src, "push", "-q", "origin", "main")
    return src


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(machine={"worktree_root": str(tmp_path / "wt"), "worktree_path": "{root}/{repo}/{run_id}"},
                  repo={"base_branch": "main", "concurrency": 4, "infra_wait_hours": 6})


def make_request(title="Bump the lint config") -> Request:
    src = Source("cli", "acme/report#1", title, "Bump it.", ["chore"], "alice", [])
    return Request("cli-1", src, "sha1", "repo", title, "chore", "explicit", None, [])


@pytest.fixture
def prs() -> FakePullRequests:
    return FakePullRequests()


@pytest.fixture
def tracker() -> FakeTracker:
    return FakeTracker()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def new_run(repo, cfg, tmp_path):
    """Creates a pending run in the factory home, with its worktree path reserved but not created."""
    def make(request: Request | None = None, run_id: str = "bump-q1w2e") -> Path:
        home = state.factory_home()
        key = state.repo_key(repo, cfg)
        ref = state.init_run(home, repo, key, run_id, request or make_request(), branch=run_id,
                             worktree=tmp_path / "wt" / repo.name / run_id,
                             kit_hash=gitops.snapshot_kit(repo, "main", home))
        return ref.run_dir
    return make


@pytest.fixture
def engine(repo, cfg, tracker, prs, clock):
    def make(script: dict, writes: dict | None = None) -> tuple[Engine, FakeWorkerAdapter]:
        worker = FakeWorkerAdapter(script, writes=writes)
        return Engine(repo, cfg, workers={"fake": worker}, command=worker, tracker=tracker, prs=prs, clock=clock), worker
    return make


def drive_triage(eng, run_dir: Path, run_id: str, workflow: str = "chore") -> None:
    """Runs one pass so triage ends and the run worktree exists. The worker for `rules` must be scripted."""
    eng.tick(run_id)


def seed_artifact(task_dir: Path, name: str, text: str = "{}") -> Path:
    path = task_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path




