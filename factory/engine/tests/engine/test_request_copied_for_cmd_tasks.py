"""ADR 2026-11-17-factory-triage-reads-its-request-from-the-task-folder: the engine copies the run's request.json into a
deterministic (cmd) task's folder before the task starts, so the command can read it inside the sandbox."""

import json

from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok

from conftest import TRIAGE_JSON


def test_the_request_is_in_the_cmd_task_folder_when_the_command_starts(new_run, repo, cfg, tracker, prs, clock):
    from factory_engine.engine import Engine
    run_dir = new_run()
    seen: dict = {}
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    command = FakeWorkerAdapter({"rules": [ok(work("rules", "triage.json"))]},
                                writes={"rules": {"triage.json": TRIAGE_JSON}})
    real_start = command.start

    def spy(ctx, conf, log):
        folder = ctx.task_dir
        seen["has_request"] = (folder / "request.json").is_file()
        if seen["has_request"]:
            seen["title"] = json.loads((folder / "request.json").read_text())["title"]
        return real_start(ctx, conf, log)

    command.start = spy
    eng = Engine(repo, cfg, workers={"claude": FakeWorkerAdapter({})}, command=command, tracker=tracker, prs=prs,
                 clock=clock)
    eng.tick("bump-q1w2e")
    assert seen == {"has_request": True, "title": "Bump the lint config"}


def test_a_skill_task_folder_gets_no_request_copy(new_run, repo, cfg, tracker, prs, clock):
    """Only deterministic tasks need the copy; the worker reads its request through its own prompt."""
    from factory_engine.engine import Engine
    run_dir = new_run()
    claude = FakeWorkerAdapter({"rules": [ok()]}, writes={})
    eng = Engine(repo, cfg, workers={"claude": claude}, command=FakeWorkerAdapter({}), tracker=tracker, prs=prs,
                 clock=clock)
    spec_ctx_ok = eng._request_copy_for(run_dir, _skill_spec())
    assert spec_ctx_ok is False


def _skill_spec():
    from factory_engine.types import HelperPolicy, TaskSpec
    return TaskSpec(id="cause", skill="root-cause", cmd=None, run=None, scope=[], deny=[], needs=[],
                    helpers=HelperPolicy("off", 0, [], None), out=None, timeout_minutes=5, retries=0, model=None,
                    when=None)
