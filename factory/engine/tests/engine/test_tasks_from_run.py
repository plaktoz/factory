"""Item 22, open gap: a stage with `tasks_from` reads the artifact an earlier task wrote, in that task's work folder."""

import json

from factory_engine import state
from factory_engine.adapters.worker.fake import ok

from engine_helpers import TRIAGE_JSON

RESEARCH = """\
name: chore
type: chore
sink: pull_request
policy: {write: true}
stages:
  - id: scope
    tasks: [{id: questions, skill: scope, out: questions.json}]
  - id: gather
    needs: [scope]
    tasks_from: questions.json
    task_template: {skill: gather, helpers: {mode: off}, timeout_minutes: 20}
"""


def test_a_templated_stage_builds_its_tasks_from_the_artifact_an_earlier_task_wrote(new_run, engine):
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    questions = [{"id": "q1", "question": "What does the vendor charge?"}, {"id": "q2", "question": "Where is it hosted?"}]
    script = {"rules": [ok(work("rules", "triage.json"))], "questions": [ok(work("questions", "questions.json"))],
              "q1": [ok(work("q1", "artifact.json"))], "q2": [ok(work("q2", "artifact.json"))]}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "questions": {"questions.json": json.dumps(questions)},
              "q1": {"artifact.json": "{}"}, "q2": {"artifact.json": "{}"}}
    eng, worker = engine(script, writes)
    wf_dir = eng.repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "chore.yaml").write_text(RESEARCH)
    eng.run(["bump-q1w2e"])
    asked = {c.task_id: c.question for c in worker.started if c.task_id in ("q1", "q2")}
    assert asked == {"q1": "What does the vendor charge?", "q2": "Where is it hosted?"}
    assert [state.read_task(run_dir, t).status for t in ("q1", "q2")] == ["done", "done"]


def test_a_tasks_from_name_that_no_task_wrote_stops_the_stage_with_a_message(new_run, engine):
    import pytest

    from factory_engine.errors import FactoryError
    run_dir = new_run()
    eng, _ = engine({})
    stage = next(s for s in eng._load("chore").stages if s.id == "implement")
    stage = type(stage)(**{**stage.__dict__, "tasks_from": "questions.json"})
    with pytest.raises(FactoryError, match="matches 0 task artifacts"):
        eng._tasks_from_artifact(run_dir, stage)


def test_a_tasks_from_name_written_by_two_tasks_stops_the_stage_with_a_message(new_run, engine):
    import pytest

    from factory_engine.errors import FactoryError
    run_dir = new_run()
    for t in ("one", "two"):
        (run_dir / "tasks" / t / "work").mkdir(parents=True)
        (run_dir / "tasks" / t / "work" / "questions.json").write_text("[]")
    eng, _ = engine({})
    stage = next(s for s in eng._load("chore").stages if s.id == "implement")
    stage = type(stage)(**{**stage.__dict__, "tasks_from": "questions.json"})
    with pytest.raises(FactoryError, match="matches 2 task artifacts"):
        eng._tasks_from_artifact(run_dir, stage)
