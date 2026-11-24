"""W0.4: the state-file schemas exist, mirror their dataclasses, and accept and refuse what they should."""

import copy
import dataclasses
import json
from pathlib import Path

import jsonschema
import pytest

from factory_engine import schemagen
from factory_engine import types as T

SCHEMAS = schemagen.SCHEMA_DIR


def load(name):
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text())


def check(name, doc):
    jsonschema.Draft202012Validator(load(name)).validate(doc)


@pytest.mark.parametrize("name", sorted(schemagen.FILE_TYPES))
def test_committed_schema_matches_its_dataclass(name):
    """Fails when types.py changes and the schema was not regenerated (python -m factory_engine.schemagen)."""
    assert (SCHEMAS / f"{name}.schema.json").read_text() == schemagen.render(name)


@pytest.mark.parametrize("name", sorted(schemagen.FILE_TYPES) + ["feedback"])
def test_each_schema_is_valid_draft_2020_12(name):
    jsonschema.Draft202012Validator.check_schema(load(name))


@pytest.mark.parametrize("name", sorted(schemagen.FILE_TYPES))
def test_schema_requires_every_dataclass_field_and_the_version(name):
    cls = schemagen.FILE_TYPES[name]
    assert load(name)["required"] == ["schema_version", *[f.name for f in dataclasses.fields(cls)]]


SOURCE = {"type": "github", "ref": "owner/payments-api#42", "title": "Login fails on expired token",
          "body": "Steps to reproduce...", "labels": ["bug"], "author": "alice", "files": []}
REQUEST = {"schema_version": 1, "request_id": "gh-42", "source": SOURCE, "body_sha": "c91e07",
           "repo": "payments-api", "title": "Login fails on expired token", "type": None, "type_source": None,
           "priority": "high", "acceptance": ["Expired token returns 401 with a refresh hint"]}
RUN = {"schema_version": 1, "run_id": "new-color-q1w2e", "repo": "payments-api", "repo_key": "github.com/acme/payments-api",
       "repo_path": "/home/me/dev/payments-api", "request": {k: v for k, v in REQUEST.items() if k != "schema_version"},
       "workflow": "bug-fix", "branch": "new-color-q1w2e", "worktree": "/home/me/dev/worktree/payments-api/new-color-q1w2e",
       "status": "running", "stage": "fix",
       "stages": [{"id": "propose", "visit": 1, "status": "done", "tasks": ["plan"], "started": "t0", "ended": "t1"},
                  {"id": "fix", "visit": 1, "status": "running", "tasks": ["backend", "frontend"], "started": "t1", "ended": None}],
       "loops": {"verify->fix": 1}, "attention": None, "pr": None, "signals": None,
       "heartbeat": "2026-11-14T10:20:12+08:00", "kit_hash": "ab12cd", "infra_wait": None,
       "paths": {"run_dir": "/h/runs/k/new-color-q1w2e", "repo": "/home/me/dev/payments-api",
                 "worktree": "/home/me/dev/worktree/payments-api/new-color-q1w2e"}}
TASK = {"schema_version": 1, "task_id": "backend", "stage": "fix", "status": "running", "attempt": 2, "restarts": 0,
        "task_base": "a1b2c3", "worktree": "/w/backend", "checkpoints": 3}
USAGE = {"schema_version": 1, "run_id": "r", "task_id": "backend", "stage": "fix", "attempt": 1, "harness": "claude",
         "model_requested": None, "models": ["claude-advantage-assist"], "input_tokens": 10, "output_tokens": 5,
         "total_tokens": 15, "start": "t0", "end": "t1", "exit": "ok", "repo": "payments-api",
         "branch": "new-color-q1w2e", "worktree": "/w"}
EVENT = {"schema_version": 1, "seq": 7, "ts": "t", "type": "gate_failed", "run_id": "r", "data": {"gate": "scope-diff"}}
FEEDBACK = {"schema_version": 1, "from_stage": "verify", "to_stage": "fix", "loop": 1, "max": 2,
            "gate": "cmd: [make, test-api]", "exit_code": 1, "failed_tests": ["test_refresh_token_expired"],
            "output_tail": "last 200 lines of the gate output", "changed_files": ["services/api/auth.py"],
            "at": "2026-11-14T10:20:00+08:00"}
GOOD = {"request": REQUEST, "run": RUN, "task": TASK, "usage": USAGE, "event": EVENT, "feedback": FEEDBACK}


@pytest.mark.parametrize("name", sorted(GOOD))
def test_valid_document_passes(name):
    check(name, GOOD[name])


@pytest.mark.parametrize("name", sorted(GOOD))
def test_missing_field_fails(name):
    doc = copy.deepcopy(GOOD[name])
    doc.pop(next(k for k in doc if k != "schema_version"))
    with pytest.raises(jsonschema.ValidationError):
        check(name, doc)


@pytest.mark.parametrize("name", sorted(GOOD))
def test_unknown_field_fails(name):
    doc = dict(GOOD[name], surprise=1)
    with pytest.raises(jsonschema.ValidationError):
        check(name, doc)


@pytest.mark.parametrize("name", sorted(GOOD))
def test_unknown_schema_version_fails(name):
    with pytest.raises(jsonschema.ValidationError):
        check(name, dict(GOOD[name], schema_version=2))


def test_a_human_rework_feedback_record_with_notes_is_valid():
    """A human rework has no gate or tests: gate "human", exit_code null, empty lists, and the operator's notes."""
    human = dict(FEEDBACK, gate="human", exit_code=None, failed_tests=[], output_tail="", changed_files=[],
                 notes="Use the refresh hint in the 401 body.")
    check("feedback", human)
    with pytest.raises(jsonschema.ValidationError):
        check("feedback", dict(FEEDBACK, notes=["not", "a", "string"]))


def test_enum_fields_are_closed():
    with pytest.raises(jsonschema.ValidationError):
        check("run", dict(RUN, status="sleeping"))
    with pytest.raises(jsonschema.ValidationError):
        check("usage", dict(USAGE, exit="maybe"))


def test_usage_tokens_may_be_null_but_not_strings():
    check("usage", dict(USAGE, input_tokens=None, output_tokens=None, total_tokens=None, models=[]))
    with pytest.raises(jsonschema.ValidationError):
        check("usage", dict(USAGE, input_tokens="10"))


def test_every_dataclass_doc_round_trips_into_its_type():
    """A document the schema accepts builds the dataclass (the dataclasses mirror the schemas)."""
    T.Event(**{k: v for k, v in EVENT.items() if k != "schema_version"})
    T.TaskState(**{k: v for k, v in TASK.items() if k != "schema_version"})
    T.UsageRecord(**{k: v for k, v in USAGE.items() if k != "schema_version"})
