from pathlib import Path

import pytest

from factory_engine import skills
from factory_engine.config import Config
from factory_engine.workflow import load_workflow

KIT = Path(__file__).resolve().parents[3]
CFG = Config(machine={}, repo={})


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    skills.use_kit(KIT)
    yield
    skills.use_kit(Path(skills.__file__).resolve().parents[2])


def review_standards(wf):
    stage = next(s for s in wf.stages if s.id == "review")
    task = next(t for t in stage.tasks if t.id == "standards")
    return task, stage


def test_reviewer_eval_loads_and_validates(tmp_path):
    wf = load_workflow(tmp_path, CFG, "reviewer-eval")
    assert wf.name == "reviewer-eval"
    assert [s.id for s in wf.stages] == ["review"]


def test_standards_task_and_gate_match_bug_fix_review_stage(tmp_path):
    eval_task, eval_stage = review_standards(load_workflow(tmp_path, CFG, "reviewer-eval"))
    fix_task, fix_stage = review_standards(load_workflow(tmp_path, CFG, "bug-fix"))
    assert (eval_task.skill, eval_task.out) == (fix_task.skill, fix_task.out)
    assert eval_stage.gate == fix_stage.gate


def test_runner_hard_codes_no_task_setting():
    runner = (KIT.parent / "scripts" / "evals" / "reviewers" / "run_trial.py").read_text()
    for literal in ('"review-standards"', '"standards.json"', "wait(handle, 600)"):
        assert literal not in runner, f"run_trial.py hard-codes {literal}; read it from reviewer-eval.yaml"
