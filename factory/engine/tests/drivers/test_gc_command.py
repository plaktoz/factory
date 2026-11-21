"""`factory gc` (module 16): shows the housekeeping plan, and only `--apply` carries it out.

The repo is a plain folder with no remote, so no push runs. An empty factory home has nothing to clean, so the
tests check the command's answer: the `--json` shape, the plan-only wording, and that `--apply` is the only switch.
"""

import json
import subprocess

import pytest

from factory_engine import cli
from factory_engine.errors import EXIT_OK


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    return r


def _gc(argv, capsys):
    code = cli.main(["gc", *argv])
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    return code, (json.loads(lines[-1]) if lines and lines[-1].startswith("{") else None)


def test_gc_without_apply_is_a_plan_only_and_says_so(repo, capsys):
    code, doc = _gc(["--repo", str(repo), "--json"], capsys)

    assert code == EXIT_OK
    assert doc["ok"] is True
    assert doc["data"]["applied"] is False
    assert doc["message"].startswith("plan only")


def test_gc_with_apply_reports_that_it_applied(repo, capsys):
    code, doc = _gc(["--repo", str(repo), "--apply", "--json"], capsys)

    assert code == EXIT_OK
    assert doc["data"]["applied"] is True
    assert doc["message"].startswith("applied")


def test_gc_json_lists_items_and_skipped_runs_as_lists(repo, capsys):
    _, doc = _gc(["--repo", str(repo), "--json"], capsys)

    assert doc["data"]["items"] == []
    assert doc["data"]["skipped"] == []
