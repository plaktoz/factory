"""Module 8's human rework and reject rows, driven by a real module 11 answer (`decisions.record`, the same path as
`factory decide`) through the engine, not by a fake Outcome. Module 8 acceptance: "each failure type maps to exactly
one handling type".
"""

import pytest

from factory_engine import decisions as D
from factory_engine import state
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
from factory_engine.engine import Engine

from engine_helpers import TRIAGE_JSON

# propose needs a human; rework goes back to root-cause, and reject ends the run.
WORKFLOW = """\
name: chore
type: chore
sink: pull_request
policy:
  write: true
  deny_paths: [".github/**"]
defaults:
  retries: 2
  timeout_minutes: 30
  checkpoint_every_minutes: 10
  max_restarts: 3
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
"""


def _engine(repo, cfg, tracker, prs, clock, run_dir):
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))],
              "cause": [ok(work("cause", "cause.json")), ok(work("cause", "cause.json"))],
              "plan": [ok(work("plan", "plan.json")), ok(work("plan", "plan.json"))],
              "change": [ok(work("change", "change.json"))]}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "cause": {"cause.json": "{}"}, "plan": {"plan.json": "{}"},
              "change": {"change.json": "{}"}}
    worker = FakeWorkerAdapter(script, writes=writes)
    eng = Engine(repo, cfg, workers={"fake": worker}, command=worker, tracker=tracker, prs=prs, clock=clock)
    wf_dir = repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "chore.yaml").write_text(WORKFLOW)
    return eng


def _answer(run_dir, choice_id):
    visit = D.latest_visit(state.read_run(run_dir), "propose")
    doc = D.read_decision(run_dir, "propose", visit)
    return D.record(run_dir, "propose", visit, packet_sha=doc["packet"]["sha"],
                    choices={d["id"]: choice_id for d in doc["packet"]["decisions"]}, by="owner", channel="cli")


def _stage(run, stage_id):
    return next((s for s in run.stages if s.id == stage_id), None)


@pytest.fixture
def waiting(new_run, repo, cfg, tracker, prs, clock):
    run_dir = new_run()
    eng = _engine(repo, cfg, tracker, prs, clock, run_dir)
    assert eng.run(["bump-q1w2e"]).runs["bump-q1w2e"] == "awaiting_approval"
    assert state.read_run(run_dir).stage == "propose"
    return run_dir, eng


def test_a_rework_answer_sends_the_run_back_to_on_reject_and_asks_again(waiting):
    run_dir, eng = waiting
    _answer(run_dir, "rework")
    result = eng.run(["bump-q1w2e"])
    run = state.read_run(run_dir)
    assert run.stage == "propose" and result.runs["bump-q1w2e"] == "awaiting_approval"
    assert _stage(run, "root-cause").visit == 2       # the target stage starts a new visit
    assert _stage(run, "fix").status == "pending"     # the stages after it start again, with no task yet
    assert run.loops == {"propose->root-cause:human": 1}
    asked = [e for e in state.read_events(run_dir) if e.type == "decision_requested" and e.data.get("stage") == "propose"]
    assert len(asked) == 2                            # the first ask, then a second one for the new visit


def test_a_reject_answer_aborts_the_run_and_no_later_stage_runs(waiting):
    run_dir, eng = waiting
    _answer(run_dir, "reject")
    result = eng.run(["bump-q1w2e"])
    run = state.read_run(run_dir)
    assert run.status == "aborted" and result.runs["bump-q1w2e"] == "aborted"
    assert _stage(run, "fix") is None
    aborted = [e.data for e in state.read_events(run_dir) if e.type == "run_aborted"]
    assert aborted == [{"reason": "rejected by a person"}]
