"""Section 20: editing `factory/workflows/` in the main checkout while a run is active does not change the run.

A run reads its kit from its snapshot (`kits/<hash>/factory`, taken from git when the run was created). The launcher
starts the run's engine with that snapshot first on the path, so `skills.KIT` is the snapshot. This test points the
engine at the snapshot the same way, then breaks the checkout's copy of the chore workflow from inside the `change`
worker, mid-run. The engine loads the workflow again on every pass, so a read of the checkout would fail the run on
the next pass.
"""

from factory_engine import skills, state
from factory_engine.adapters.worker.fake import FakeWorkerAdapter
from factory_engine.engine import Engine

from engine_helpers import chore_script

BROKEN = "name: [this is not a workflow\n"


class EditsTheCheckoutMidRun(FakeWorkerAdapter):
    """The `change` task writes a broken chore workflow into the main checkout while the run is active."""

    def __init__(self, script, writes, checkout_workflow):
        super().__init__(script, writes=writes)
        self.checkout_workflow = checkout_workflow

    def start(self, ctx, conf, log):
        handle = super().start(ctx, conf, log)
        if ctx.task_id == "change":
            self.checkout_workflow.write_text(BROKEN)
        return handle


def test_a_run_keeps_using_its_kit_snapshot_when_the_checkout_workflow_changes_mid_run(new_run, repo, cfg, tracker, prs,
                                                                                     clock):
    run_dir = new_run()
    kit_hash = state.read_run(run_dir).kit_hash
    skills.use_kit(state.factory_home() / "kits" / kit_hash / "factory")  # the engine's kit, as the launcher sets it
    checkout_workflow = repo / "factory" / "workflows" / "chore.yaml"
    script, writes = chore_script(run_dir)
    worker = EditsTheCheckoutMidRun(script, writes, checkout_workflow)
    eng = Engine(repo, cfg, workers={"fake": worker}, command=worker, tracker=tracker, prs=prs, clock=clock)

    result = eng.run(["bump-q1w2e"])

    assert checkout_workflow.read_text() == BROKEN  # the edit happened while the run was active
    run = state.read_run(run_dir)
    assert result.runs == {"bump-q1w2e": "awaiting_approval"}
    assert [s.id for s in run.stages] == ["triage", "implement", "verify"]
    assert [s.status for s in run.stages] == ["done", "done", "done"]
