"""Item 63, step 2: the engine records the process group of a running worker in task.json, and clears it when the attempt
ends. The real CommandAdapter runs a `cmd` task under srt; the triage task stays on a fake, as in the other engine tests.

The worker process is real and is killed in a `finally` if the test fails before it ends.
"""

import json
import os
import shutil
import sys

import pytest

from factory_engine import state
from factory_engine.adapters.worker import sandbox
from factory_engine.adapters.worker.command import CommandAdapter
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok

from engine_helpers import TRIAGE_JSON

needs_srt = pytest.mark.skipif(shutil.which("srt") is None or sandbox.node_version() is None
                               or sandbox.node_version()[:2] < (22, 12),
                               reason="srt 0.0.83 and Node 22.12+ are required (module 9)")

# The `change` task writes its artifact after a short sleep, so the engine can read task.json while the worker runs.
CHANGE_CMD = [sys.executable, "-c",
              "import os, pathlib, time; time.sleep(1); "
              "pathlib.Path(os.environ['FACTORY_TASK_DIR'], 'change.json').write_text('{}')"]
CHORE_WITH_CMD_TASK = f"""name: chore
type: chore
sink: pull_request
policy: {{write: true}}
stages:
  - id: change
    tasks: [{{id: change, cmd: {json.dumps(CHANGE_CMD)}, out: change.json}}]
"""


def _alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


@needs_srt
def test_a_running_command_worker_records_its_process_group_and_the_attempt_end_clears_it(new_run, repo, cfg, tracker,
                                                                                         prs, clock):
    from factory_engine.engine import Engine
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    triage = FakeWorkerAdapter({"rules": [ok(work("rules", "triage.json"))]},
                               writes={"rules": {"triage.json": TRIAGE_JSON}})
    real = CommandAdapter(dict(os.environ))
    seen: dict = {}

    class Router:
        """Triage goes to the fake; every other task goes to the real CommandAdapter."""
        name = "command"
        capabilities = real.capabilities

        def check(self, conf):
            return real.check(conf)

        def start(self, ctx, conf, log):
            return triage.start(ctx, conf, log) if ctx.task_id == "rules" else real.start(ctx, conf, log)

        def wait(self, handle, timeout_s):
            if handle.task_id == "rules":
                return triage.wait(handle, timeout_s)
            seen["pid"] = handle.data["proc"].pid
            seen["pgid_while_running"] = state.read_task(run_dir, handle.task_id).worker_pgid
            return real.wait(handle, timeout_s)

        def stop(self, handle):
            real.stop(handle)

    wf_dir = repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "chore.yaml").write_text(CHORE_WITH_CMD_TASK)
    try:
        eng = Engine(repo, cfg, workers={"claude": FakeWorkerAdapter({})}, command=Router(), tracker=tracker, prs=prs,
                     clock=clock)
        eng.run(["bump-q1w2e"])
        assert seen["pgid_while_running"] == seen["pid"]  # start_new_session: the group leader's pid is the group id
        assert state.read_task(run_dir, "change").worker_pgid is None
    finally:
        if "pid" in seen and _alive(seen["pid"]):
            os.killpg(seen["pid"], 9)


def test_a_fake_worker_has_no_process_group_so_none_is_recorded(new_run, repo, cfg, tracker, prs, clock):
    from factory_engine.engine import Engine
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    seen: dict = {}
    command = FakeWorkerAdapter({"rules": [ok(work("rules", "triage.json"))]},
                                writes={"rules": {"triage.json": TRIAGE_JSON}})
    real_wait = command.wait

    def spy_wait(handle, timeout_s):
        seen["pgid"] = state.read_task(run_dir, handle.task_id).worker_pgid
        return real_wait(handle, timeout_s)

    command.wait = spy_wait
    Engine(repo, cfg, workers={"claude": FakeWorkerAdapter({})}, command=command, tracker=tracker, prs=prs,
           clock=clock).tick("bump-q1w2e")
    assert seen == {"pgid": None}
