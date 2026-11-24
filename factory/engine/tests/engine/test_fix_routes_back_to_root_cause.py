"""Module 11, a second visit: when `fix` fails its gate and its on_fail edge goes back to root-cause, the run goes through
propose again. Propose gets a new decision file (propose.2.yaml) that needs a fresh approval, and propose.1.yaml is left
byte for byte as the person answered it. The route is the real engine loop (module 6B), not a fake Outcome."""

from factory_engine import decisions as D
from factory_engine import gates
from factory_engine import state
from factory_engine.adapters.worker.fake import ok

from engine_helpers import TRIAGE_JSON

WORKFLOW = """\
name: chore
type: chore
sink: pull_request
policy: {write: true, deny_paths: []}
defaults: {retries: 0, timeout_minutes: 5, checkpoint_every_minutes: 10, max_restarts: 0}
stages:
  - id: root-cause
    tasks: [{id: cause, skill: root-cause, out: cause.json}]
  - id: propose
    needs: [root-cause]
    tasks: [{id: plan, skill: propose, out: plan.json}]
    approval: human
    on_reject: {goto: root-cause}
  - id: fix
    needs: [propose]
    tasks: [{id: change, skill: implement, out: change.json}]
    gate: [{cmd: [make, build]}]
    on_fail: {goto: root-cause, max: 2}
"""


class BuildFailsOnce:
    """The `make build` gate: fails the first time it runs, passes after that. It replaces only the command runner;
    the gate result, the routing and the decision files are the engine's own."""

    def __init__(self):
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, ctx):
        self.calls.append(tuple(argv))
        return (1, "build broke") if len(self.calls) == 1 else (0, "")


def _answer(run_dir, stage, visit, choice_id):
    doc = D.read_decision(run_dir, stage, visit)
    return D.record(run_dir, stage, visit, packet_sha=doc["packet"]["sha"],
                    choices={d["id"]: choice_id for d in doc["packet"]["decisions"]}, by="owner", channel="cli")


def test_a_fix_failure_routed_to_root_cause_asks_again_and_leaves_the_first_file_alone(new_run, engine, repo):
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))],
              "cause": [ok(work("cause", "cause.json"))] * 2,
              "plan": [ok(work("plan", "plan.json"))] * 2,
              "change": [ok(work("change", "change.json"))]}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "cause": {"cause.json": "{}"},
              "plan": {"plan.json": "{}"}, "change": {"change.json": "{}"}}
    eng, _ = engine(script, writes)
    wf_dir = repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "chore.yaml").write_text(WORKFLOW)

    assert eng.run(["bump-q1w2e"]).runs["bump-q1w2e"] == "awaiting_approval"
    _answer(run_dir, "propose", 1, "approve")
    first = D.decision_path(run_dir, "propose", 1).read_bytes()

    build = BuildFailsOnce()
    with gates.use_command_runner(build):
        result = eng.run(["bump-q1w2e"])

    assert build.calls == [("make", "build")]           # the gate ran once, failed, and routed the run back
    run = state.read_run(run_dir)
    assert result.runs["bump-q1w2e"] == "awaiting_approval"
    assert run.stage == "propose" and run.loops == {"fix->root-cause": 1}
    assert D.latest_visit(run, "propose") == 2
    assert D.decision_path(run_dir, "propose", 2).name == "propose.2.yaml"
    assert D.evaluate(run_dir, "propose", 2).status == "pending"       # a fresh approval is needed
    assert D.decision_path(run_dir, "propose", 1).read_bytes() == first  # propose.1.yaml is unchanged
    assert D.evaluate(run_dir, "propose", 1).status == "approved"
