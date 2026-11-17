"""Item 12, gap 2: with no stub installed, a `cmd` gate runs through CommandAdapter under srt (module 8, Gate commands
run sandboxed). These tests run a real command, so they need srt and Node 22.12 or later (module 9)."""

import os
import shutil
import sys
from pathlib import Path

import pytest

from factory_engine import gates
from factory_engine.adapters.worker import sandbox
from factory_engine.config import Config
from factory_engine.errors import FactoryError
from factory_engine.state import init_run, read_run
from factory_engine.types import GateContext, GateSpec, Request, Source

needs_srt = pytest.mark.skipif(shutil.which("srt") is None or sandbox.node_version() is None
                               or sandbox.node_version()[:2] < (22, 12),
                               reason="srt 0.0.83 and Node 22.12+ are required (module 9)")


@pytest.fixture(autouse=True)
def factory_home(tmp_path, monkeypatch):
    home = tmp_path / "factory-home"
    home.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(home))
    return home


def _ctx(tmp_path: Path) -> GateContext:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    rq = Request("gh-1", Source("cli", "x", "t", "b", [], None, []), "sha", "repo", "t", "bug", None, None, [])
    ref = init_run(tmp_path / "home", tmp_path, "local/repo", "run-1", rq, branch="run-1", worktree=worktree, kit_hash="x")
    run = read_run(ref.run_dir)
    return GateContext(run=run, stage="verify", task_id="be-tests", worktree=worktree,
                       task_dir=ref.run_dir / "tasks" / "be-tests" / "work", artifact=None, task_base=None, scope=[],
                       deny=[], cfg=Config(machine={}, repo={}))


def _gate(argv: list[str]) -> GateSpec:
    return GateSpec(kind="cmd", cmd=argv, check=None, schema=None, args={})


@needs_srt
def test_a_cmd_gate_runs_a_real_command_through_command_adapter_when_no_runner_is_installed(tmp_path):
    ctx = _ctx(tmp_path)
    (result,) = gates.run_gates([_gate([sys.executable, "-c", "print('built')"])], ctx)
    assert result.passed and result.details["exit_code"] == 0


@needs_srt
def test_a_real_command_that_exits_non_zero_fails_the_gate_and_returns_its_output(tmp_path):
    ctx = _ctx(tmp_path)
    (result,) = gates.run_gates([_gate([sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"])], ctx)
    assert not result.passed and result.code == "gate.exit_code"
    assert result.details["exit_code"] == 3 and "boom" in result.output_tail


@needs_srt
def test_a_real_gate_command_that_is_not_installed_is_a_task_error_not_a_failed_gate(tmp_path):
    ctx = _ctx(tmp_path)
    with pytest.raises(FactoryError) as err:
        gates.run_gates([_gate(["definitely-not-a-real-binary-xyz"])], ctx)
    assert err.value.code == "gate.command_missing" and err.value.kind == "human"


@needs_srt
def test_a_real_gate_command_cannot_read_the_factory_home(tmp_path, factory_home):
    secret = factory_home / "secret.txt"
    secret.write_text("hunter2")
    ctx = _ctx(tmp_path)
    (result,) = gates.run_gates([_gate(["cat", str(secret)])], ctx)
    assert not result.passed and "hunter2" not in result.output_tail
