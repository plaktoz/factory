"""Item 12, gap 4: a cmd task that exits 0 has its artifact returned by wait, when its `out` file exists in the task
folder (module 9: a command's artifact goes in FACTORY_TASK_DIR). Without one, wait returns no artifact, so the engine
does not mark the task done (engine._record_result)."""

import os
import shutil

import pytest

from factory_engine.adapters.worker import sandbox
from factory_engine.adapters.worker.command import CommandAdapter

from workers_helpers import harness

needs_srt = pytest.mark.skipif(shutil.which("srt") is None or sandbox.node_version() is None
                               or sandbox.node_version()[:2] < (22, 12),
                               reason="srt 0.0.83 and Node 22.12+ are required (module 9)")


@pytest.fixture
def cmd_ctx(make_ctx):
    def make(**kw):
        ctx = make_ctx(**{k: v for k, v in kw.items() if k in ("task_id", "attempt", "bash")})
        ctx.skill = None
        ctx.cmd = kw.get("cmd")
        ctx.artifact_name = kw.get("artifact_name", "artifact.json")
        return ctx
    return make


def _run(ctx, tmp_path):
    adapter = CommandAdapter(dict(os.environ))
    handle = adapter.start(ctx, harness("command"), tmp_path / "worker.log")
    return adapter.wait(handle, 60)


@needs_srt
def test_a_cmd_that_writes_its_out_file_returns_that_file_as_the_artifact(cmd_ctx, tmp_path, factory_home, task_dir):
    out = task_dir / "be.junit.xml"
    result = _run(cmd_ctx(cmd=["sh", "-c", f"printf '<testsuite/>' > {out}"], artifact_name="be.junit.xml"), tmp_path)
    assert result.exit == "ok" and result.exit_code == 0
    assert result.artifact == out and out.read_text() == "<testsuite/>"


@needs_srt
def test_a_cmd_that_writes_no_out_file_returns_no_artifact(cmd_ctx, tmp_path, factory_home, task_dir):
    result = _run(cmd_ctx(cmd=["true"], artifact_name="never.json"), tmp_path)
    assert result.exit == "ok" and result.artifact is None
