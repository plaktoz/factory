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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workers_helpers import HERE, RECORDED, ctx_for  # noqa: E402



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
        """Keys: result (a recorded JSON file), stderr, exit, sleep, artifact ([name, text]), helpers, early_out, early_err."""
        base = {"result": str(RECORDED / "ok.json"), "stderr": "", "exit": 0, "sleep": 0, "artifact": None,
                "helpers": 0, "early_out": "", "early_err": "", "record": str(self.record)}
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








@pytest.fixture
def make_ctx(worktree, task_dir):
    def make(**kw):
        return ctx_for(worktree, task_dir, **kw)
    return make




