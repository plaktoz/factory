"""Item 12, gap 1: a `cmd` task goes to CommandAdapter; a `skill` task goes to the worker registered for its harness.

The command adapter is a fake here, so this checks routing only. Whether srt really runs the command is tested in
tests/workers/test_command_adapter.py.
"""

import json

from factory_engine import state
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok

from conftest import TRIAGE_JSON  # noqa: F401  (documents the triage answer the fixtures write)


def test_a_cmd_task_is_handed_to_the_command_adapter_and_not_to_the_worker(new_run, repo, cfg, tracker, prs, clock):
    from factory_engine.engine import Engine
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    claude = FakeWorkerAdapter({"rules": [ok(work("rules", "triage.json"))]},
                               writes={"rules": {"triage.json": TRIAGE_JSON}})
    command = FakeWorkerAdapter({"rules": [ok(work("rules", "triage.json"))]},
                                writes={"rules": {"triage.json": TRIAGE_JSON}})
    eng = Engine(repo, cfg, workers={"claude": claude}, command=command, tracker=tracker, prs=prs, clock=clock)
    eng.tick("bump-q1w2e")
    assert [c.task_id for c in command.started] == ["rules"]
    assert claude.started == []


def test_a_skill_task_still_goes_to_the_registered_worker(new_run, repo, cfg, tracker, prs, clock):
    from factory_engine.engine import Engine
    new_run()
    claude = FakeWorkerAdapter({"rules": [ok()]}, writes={})
    command = FakeWorkerAdapter({}, writes={})
    eng = Engine(repo, cfg, workers={"claude": claude}, command=command, tracker=tracker, prs=prs, clock=clock)
    assert eng._worker_for(_spec(skill="classify", cmd=None)) is claude


def _spec(**kw):
    from factory_engine.types import HelperPolicy, TaskSpec
    base = dict(id="t", skill=None, cmd=None, run=None, scope=[], deny=[], needs=[],
                helpers=HelperPolicy("off", 0, [], None), out=None, timeout_minutes=5, retries=0, model=None, when=None)
    return TaskSpec(**{**base, **kw})
