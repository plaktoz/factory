"""`factory triage` runs as the `rules` task of the triage stage, in the task folder, which is not a git repo.

The shipped _triage workflow calls `factory triage` with no arguments. The launcher used to send it through the run
path, which needs the current folder to be a git repo, so the task failed with config.invalid and the run blocked at
triage. This test runs the real launcher from a folder that is not a repo.
"""

import json

import pytest

from factory_launcher import cli


@pytest.fixture
def task_folder(tmp_path, monkeypatch):
    """A task folder with a request.json, the way the engine copies one in, and no git repo above it."""
    folder = tmp_path / "task"
    folder.mkdir()
    (folder / "request.json").write_text(json.dumps({
        "request_id": "r1",
        "source": {"type": "cli", "ref": "r1", "title": "Fix add() so it returns the sum", "body": ""},
        "body_sha": "x", "repo": "repo", "title": "Fix add() so it returns the sum", "type": "chore",
        "type_source": "explicit", "priority": None, "acceptance": [],
    }))
    monkeypatch.setenv("FACTORY_TASK_DIR", str(folder))
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)  # not a git repo, the way a task folder is not one
    return folder


def test_factory_triage_writes_triage_json_from_a_folder_that_is_not_a_repo(task_folder, capsys):
    assert cli.main(["triage"]) == 0
    doc = json.loads((task_folder / "triage.json").read_text())
    assert doc["type"] == "chore"
    assert "triage.json written" in capsys.readouterr().out


def test_triage_still_refuses_when_the_task_folder_is_not_set(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("FACTORY_TASK_DIR", raising=False)
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    assert cli.main(["triage", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "config.invalid"
