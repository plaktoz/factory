"""Item 12, the real route: the `rules` task is `factory triage` run by CommandAdapter under srt. The engine copies
request.json into the task folder, srt confines the command to that folder and the worktree, and triage.json must come
back. This is the one test that shows the sandbox lets the command read its request (ADR 2026-11-17)."""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from factory_engine.adapters.worker import sandbox
from factory_engine.adapters.worker.base import HarnessConfig
from factory_engine.adapters.worker.command import CommandAdapter
from factory_engine.types import Request, Source
from factory_engine.state import _dataclass_doc
from factory_engine.triage_cli import REQUEST_FILE


ENGINE_DIR = Path(__file__).resolve().parents[2]

# `python -m factory_engine triage`, from the checkout under test. The adapter passes the child no PYTHONPATH, so the
# child would otherwise import whatever the virtualenv's editable install points at, which may be another checkout.
_RUN_THIS_CHECKOUTS_TRIAGE = ("import runpy, sys; sys.path.insert(0, sys.argv[1]); sys.argv = ['factory_engine', 'triage']; "
                              "runpy.run_module('factory_engine', run_name='__main__', alter_sys=True)")

needs_srt = pytest.mark.skipif(shutil.which("srt") is None or sandbox.node_version() is None
                               or sandbox.node_version()[:2] < (22, 12),
                               reason="srt 0.0.83 and Node 22.12+ are required (module 9)")


@needs_srt
def test_factory_triage_run_under_srt_reads_the_copied_request_and_writes_triage_json(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "factory-home"))
    worktree = tmp_path / "wt"
    worktree.mkdir()
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    req = Request("cli-9", Source("cli", "acme/app#9", "Fix the crash", "A bug in the parser.", [], None, []),
                  "sha", "app", "Fix the crash", None, None, None, [])
    (task_dir / REQUEST_FILE).write_text(json.dumps({"schema_version": 1, **_dataclass_doc(req)}))

    ctx = _task_context(worktree, task_dir, cmd=[sys.executable, "-c", _RUN_THIS_CHECKOUTS_TRIAGE, str(ENGINE_DIR)])
    env = dict(os.environ)
    env["FACTORY_TASK_DIR"] = str(task_dir)
    adapter = CommandAdapter(env)
    handle = adapter.start(ctx, HarnessConfig("command", None, [], {}), tmp_path / "worker.log")
    result = adapter.wait(handle, 120)
    assert result.exit == "ok", (result, (tmp_path / "worker.log").read_text() if (tmp_path / "worker.log").is_file() else "")
    assert result.artifact == task_dir / "triage.json"
    doc = json.loads((task_dir / "triage.json").read_text())
    assert doc["type"] == "bug" and doc["workflow"] == "bug-fix"


def _task_context(worktree: Path, task_dir: Path, *, cmd: list[str]):
    from factory_engine.adapters.worker.base import TaskContext
    from factory_engine.types import HelperPolicy
    rq = Request("cli-9", Source("cli", "acme/app#9", "Fix the crash", "A bug in the parser.", [], None, []),
                 "sha", "app", "Fix the crash", None, None, None, [])
    return TaskContext(run_id="run-1", task_id="rules", stage="triage", attempt=1, skill=None, request=rq,
                       worktree=worktree, task_dir=task_dir, scope=[], deny=[], helpers=HelperPolicy("off", 0, [], None),
                       feedback=[], notes=[], progress=None, output_schema=None, model=None, mcp=[], practices=[],
                       artifact_name="triage.json", cmd=cmd)
