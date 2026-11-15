"""Shared fixtures for the worker adapter tests (module 9).

Each real adapter is tested against a stub executable that replays recorded JSON (`stub_claude.py`), never the live CLI.
The live smoke test is the only one that calls the real `claude`, and it runs only when FACTORY_LIVE=1.
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from factory_engine.adapters.worker.base import HarnessConfig, TaskContext
from factory_engine.skills import SkillRef
from factory_engine.types import HelperPolicy, Request, Source

HERE = Path(__file__).resolve().parent
RECORDED = HERE / "recorded"
ENV_GW = {"ANTHROPIC_AUTH_TOKEN": "tok-gateway-SECRET-123", "ANTHROPIC_BASE_URL": "https://gw.example.test"}


class Stub:
    """One stub `claude`: its directory, the config the next run reads, and the folder it records into."""

    def __init__(self, bindir: Path):
        self.bindir = bindir
        self.record = bindir / "record"
        self.config_path = bindir / "stub_config.json"
        self.exe = bindir / "claude"
        # The wrapper runs the stub with its config next to the wrapper, so a test's config is the one the stub reads.
        self.exe.write_text(
            f"#!/bin/sh\nexec {sys.executable} -I {HERE / 'stub_claude.py'} {self.config_path} \"$@\"\n")
        self.exe.chmod(self.exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.set(result=str(RECORDED / "ok.json"))

    def set(self, **cfg) -> "Stub":
        """Keys: result (a recorded JSON file), stderr, exit, sleep, artifact ([name, text]), helpers."""
        base = {"result": str(RECORDED / "ok.json"), "stderr": "", "exit": 0, "sleep": 0, "artifact": None,
                "helpers": 0, "record": str(self.record)}
        base.update(cfg)
        self.config_path.write_text(json.dumps(base))
        return self

    def seen(self, name: str) -> str:
        return (self.record / name).read_text()

    def argv(self) -> list[str]:
        return self.seen("argv.txt").splitlines()

    def env(self) -> dict:
        return json.loads(self.seen("env.json"))


@pytest.fixture
def factory_home(tmp_path, monkeypatch):
    """A factory home under tmp_path, so the tests never touch ~/.factory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(home))
    return home


@pytest.fixture
def stub(tmp_path) -> Stub:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    return Stub(bindir)


@pytest.fixture
def machine(stub, tmp_path) -> dict:
    """The machine environment: the stub's folder first on PATH, a home folder, and nothing else."""
    return {"PATH": f"{stub.bindir}:/usr/bin:/bin", "HOME": str(tmp_path / "userhome")}


@pytest.fixture
def worktree(tmp_path) -> Path:
    wt = tmp_path / "wt"
    wt.mkdir()
    return wt


@pytest.fixture
def task_dir(tmp_path) -> Path:
    d = tmp_path / "run" / "tasks" / "backend" / "work"
    d.mkdir(parents=True)
    return d


def request() -> Request:
    src = Source("cli", "acme/report#1", "Fix the total", "The total is wrong.", ["bug"], "alice", [])
    return Request("gh-1", src, "sha", "report", "Fix the total", "bug", "label", "high", ["total matches the sum"])


_DEFAULT = object()


def ctx_for(worktree: Path, task_dir: Path, *, task_id: str = "backend", attempt: int = 1,
            model: str | None = None, helpers: HelperPolicy | None = None, mcp=None, bash=None,
            artifact_name: str = "stage.json", skill=_DEFAULT) -> TaskContext:
    """A task context for an LLM stage by default. Pass skill=None for a deterministic task."""
    if skill is _DEFAULT:
        skill = SkillRef("fix", "own", worktree.parent / "skill", {})
    return TaskContext(run_id="run-1", task_id=task_id, stage="fix", attempt=attempt, skill=skill, request=request(),
                       worktree=worktree, task_dir=task_dir, scope=["src/**"], deny=["secrets/**"],
                       helpers=helpers or HelperPolicy("off", 0, [], None), feedback=[], notes=[], progress=None,
                       output_schema="stage-report", model=model, mcp=list(mcp or []), practices=[],
                       artifact_name=artifact_name, bash=list(bash or []))


@pytest.fixture
def make_ctx(worktree, task_dir):
    def make(**kw):
        return ctx_for(worktree, task_dir, **kw)
    return make


def harness(command: str, env: dict | None = None, model: str | None = None, args: list | None = None) -> HarnessConfig:
    return HarnessConfig(command=command, model=model, args=list(args or []), env=dict(env or {}))
