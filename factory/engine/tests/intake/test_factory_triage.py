"""Item 12, factory triage (ADR 2026-11-17-factory-triage-reads-its-request-from-the-task-folder).

The engine copies the run's request.json into a deterministic task's folder before it starts. `factory triage` reads
$FACTORY_TASK_DIR/request.json and writes $FACTORY_TASK_DIR/triage.json, and never reads the factory home.
"""

import json
import os
from pathlib import Path

from factory_engine import triage
from factory_engine.types import Request, Source


def _request(**over) -> Request:
    src = Source("cli", "acme/app#9", over.pop("title", "Fix the crash"), over.pop("body", "It crashes."), [], None, [])
    base = dict(request_id="cli-9", source=src, body_sha="sha", repo="app", title=src.title, type=None,
                type_source=None, priority=None, acceptance=[])
    return Request(**{**base, **over})


def _write_request(folder: Path, req: Request) -> None:
    from factory_engine.state import _dataclass_doc
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "request.json").write_text(json.dumps({"schema_version": 1, **_dataclass_doc(req)}))


def test_the_command_writes_triage_json_from_the_request_in_its_task_folder(tmp_path, monkeypatch):
    from factory_engine.triage_cli import run_triage
    task = tmp_path / "task"
    _write_request(task, _request(title="Fix the crash", body="A bug in the parser."))
    monkeypatch.setenv("FACTORY_TASK_DIR", str(task))
    assert run_triage() == 0
    doc = json.loads((task / "triage.json").read_text())
    assert doc["type"] == "bug" and doc["workflow"] == "bug-fix"
    assert doc["type_source"] == "keyword" and doc["confidence"] == 0.9 and doc["schema_version"] == 1


def test_a_request_with_no_decisive_rule_writes_null_type_for_the_classify_task(tmp_path, monkeypatch):
    from factory_engine.triage_cli import run_triage
    task = tmp_path / "task"
    _write_request(task, _request(title="Something", body="Nothing a rule matches."))
    monkeypatch.setenv("FACTORY_TASK_DIR", str(task))
    assert run_triage() == 0
    doc = json.loads((task / "triage.json").read_text())
    assert doc["type"] is None and doc["workflow"] is None and doc["confidence"] == 0.0


def test_the_command_refuses_without_a_task_folder(monkeypatch):
    from factory_engine.errors import FactoryError
    from factory_engine.triage_cli import run_triage
    monkeypatch.delenv("FACTORY_TASK_DIR", raising=False)
    import pytest
    with pytest.raises(FactoryError) as err:
        run_triage()
    assert err.value.code == "config.invalid"


def test_the_command_refuses_a_task_folder_with_no_request(tmp_path, monkeypatch):
    from factory_engine.errors import FactoryError
    from factory_engine.triage_cli import run_triage
    import pytest
    monkeypatch.setenv("FACTORY_TASK_DIR", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    with pytest.raises(FactoryError) as err:
        run_triage()
    assert err.value.code == "config.invalid" and "request.json" in err.value.message
