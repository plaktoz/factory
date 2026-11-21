"""Module 10's waiting criterion, run through module 9: each own skill runs its real prompt against FakeWorkerAdapter.

Module 10's log says the criterion "each own skill, run against FakeWorkerAdapter, writes an artifact that passes its
schema or a decision packet" needed the worker path. This file is that path. What it proves is the wiring: the prompt
the engine builds names the skill and the artifact file the task gives, and an artifact the fake writes (the skill's
output, scripted here) passes the schema it names. A fake cannot show that a model writes a good artifact. That check
needs a live run, and it is not claimed here.

Three schemas are not in the spec's fields (stage-report, review-findings, source-notes). Those artifacts are checked
for the wiring only, and the report says so (module 10 and the brief forbid inventing their fields).
"""

import json
from pathlib import Path

import pytest

from factory_engine.adapters.worker.base import HarnessConfig
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
from factory_engine.prompt import build_prompt
from factory_engine.skills import resolve_skill
from factory_engine.validate import validate
from factory_engine.config import Config

from conftest import ctx_for

KIT = Path(__file__).resolve().parents[3]  # factory/
OWN = KIT / "skills" / "own"
REPO_SKILL_STAGES = ["classify", "reproduce", "root-cause", "propose", "architect", "implement", "fix",
                     "review-standards", "review-spec", "scope", "gather", "synthesize", "critique"]
CFG = Config(machine={}, repo={})

# The artifact each skill writes, and the schema it must pass where the spec gives one.
ARTIFACT = {
    "classify": ("triage.json", "triage"),
    "architect": ("packet.json", "packet"),
}


def schema_checkable(stage: str) -> bool:
    return stage in ARTIFACT


def scripted_artifact(stage: str) -> str:
    """A well-formed artifact for the two schemas the spec gives. Other stages get a plain stub the wiring test reads."""
    if stage == "classify":
        return json.dumps({"schema_version": 1, "type": "bug", "workflow": "fix", "confidence": 0.9,
                           "type_source": "llm"})
    if stage == "architect":
        option = {"id": "a", "name": "A", "flow": ["step"], "pros": ["fast"], "cons": ["new"]}
        return json.dumps({"stage": "architect", "sha": "abc", "decisions": [{
            "id": "d1", "title": "Framework", "question": "Which framework?",
            "context": {"what": "The stack", "example": "x", "terms": {"term": "meaning"}},
            "compare": {"a": "A", "b": "B", "rows": [["speed", "fast", "slow"]],
                        "choose_a_if": "speed matters", "choose_b_if": "tooling matters"},
            "recommend": "a", "why": "speed", "options": [option, {**option, "id": "b", "name": "B"}]}]})
    return json.dumps({"schema_version": 1, "stage": stage})


@pytest.fixture
def repo(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(home))
    r = tmp_path / "repo"
    r.mkdir()
    return r


@pytest.mark.parametrize("stage", REPO_SKILL_STAGES)
def test_each_own_skill_resolves_and_its_prompt_names_the_skill_and_artifact(stage, repo, tmp_path, worktree, task_dir):
    from factory_engine import skills
    skills.use_kit(KIT)
    ref = resolve_skill(stage, repo, CFG)
    assert ref.source == "own"
    artifact = ARTIFACT.get(stage, (f"{stage}.json", None))[0]
    ctx = ctx_for(worktree, task_dir, skill=ref, artifact_name=artifact)
    text = build_prompt(ctx)
    assert f"factory-{ref.name}" in text
    assert str(task_dir / artifact) in text


@pytest.mark.parametrize("stage", REPO_SKILL_STAGES)
def test_each_own_skill_runs_against_the_fake_and_its_artifact_is_written(stage, repo, tmp_path, worktree, task_dir):
    from factory_engine import skills
    skills.use_kit(KIT)
    ref = resolve_skill(stage, repo, CFG)
    artifact, _ = ARTIFACT.get(stage, (f"{stage}.json", None))
    fake = FakeWorkerAdapter({"backend": [ok(task_dir / artifact)]},
                             writes={"backend": {artifact: scripted_artifact(stage)}})
    ctx = ctx_for(worktree, task_dir, skill=ref, artifact_name=artifact)
    conf = HarnessConfig("fake", None, [], {})
    h = fake.start(ctx, conf, tmp_path / "worker.log")
    result = fake.wait(h, 60)
    assert result.exit == "ok"
    assert (task_dir / artifact).is_file()
    assert fake.started[-1].skill.name == ref.name


@pytest.mark.parametrize("stage", sorted(ARTIFACT))
def test_the_artifact_from_the_fake_passes_the_schema_the_spec_names(stage, repo, tmp_path, worktree, task_dir):
    artifact, schema = ARTIFACT[stage]
    body = json.loads(scripted_artifact(stage))
    validate(body, schema, file=artifact)  # raises config.invalid naming the failing path


@pytest.mark.parametrize("stage", sorted(ARTIFACT))
def test_a_malformed_artifact_fails_the_schema(stage, tmp_path):
    artifact, schema = ARTIFACT[stage]
    with pytest.raises(Exception) as e:
        validate({"not": "the shape"}, schema, file=artifact)
    assert "config.invalid" in str(getattr(e.value, "code", e.value)) or "invalid" in str(e.value)


def test_every_own_skill_asks_nothing_and_says_so_in_its_rules():
    for stage in REPO_SKILL_STAGES:
        text = (OWN / stage / "SKILL.md").read_text()
        assert "Never ask a question" in text, stage


def test_the_four_report_schemas_are_accepted_phase_1_schemas_with_no_draft_marker():
    """The owner accepted the drafts as the phase 1 schemas (wave 3, D1). Each file exists, is a valid schema, and no
    longer says it is a draft, so nobody mistakes an accepted schema for one under review."""
    import jsonschema
    schema_dir = KIT / "schemas"
    for name in ("stage-report", "review-findings", "source-notes", "test-report"):
        doc = json.loads((schema_dir / f"{name}.schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(doc)
        assert "x-status" not in doc, name
        assert "DRAFT" not in doc["description"] and "NOT SPEC-BACKED" not in doc["description"], name
