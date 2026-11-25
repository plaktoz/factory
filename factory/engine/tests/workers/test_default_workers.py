"""Module 3 row `2026-11-24-a-repo-may-choose-codex` and P2-1: a repo that sets `harness: codex` gets the Codex adapter.

Nothing here runs a `codex` binary or calls a model: `default_workers` only builds the adapter, and the adapter's
binary is never started. The live smoke test is tests/workers/test_live_codex_smoke.py, run only with FACTORY_LIVE=1.
"""

import pytest

from factory_engine import api
from factory_engine.adapters.worker.claude import ClaudeAdapter
from factory_engine.adapters.worker.codex import CodexAdapter
from factory_engine.errors import FactoryError
from factory_engine.loadcfg import load_config


def _repo(tmp_path, harness: str):
    repo = tmp_path / "repo"
    (repo / ".factory" / "config").mkdir(parents=True)
    (repo / ".factory" / "config" / "factory.yaml").write_text(
        f"base_branch: main\ntracker: file\nharness: {harness}\n")
    return repo


def _home(tmp_path, machine_yaml: str | None):
    home = tmp_path / "home"
    home.mkdir()
    if machine_yaml is not None:
        (home / "config.yaml").write_text(machine_yaml)
    return home


CODEX_MACHINE = ("harnesses:\n  codex:\n    command: codex\n    model: gpt-5\n"
                 "    env:\n      OPENAI_API_KEY: ${OPENAI_API_KEY}\n")


def test_a_repo_that_chooses_codex_gets_the_codex_adapter(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(_home(tmp_path, CODEX_MACHINE)))
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    cfg = load_config(_repo(tmp_path, "codex"))
    workers = api.default_workers(cfg)
    assert list(workers) == ["codex"]
    assert isinstance(workers["codex"], CodexAdapter)


def test_a_repo_that_chooses_codex_without_a_codex_machine_entry_is_refused_with_the_resolve_message(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(_home(tmp_path, None)))
    cfg = load_config(_repo(tmp_path, "codex"))
    with pytest.raises(FactoryError) as e:
        api.default_workers(cfg)
    assert e.value.code == "config.invalid" and "is not in the machine file" in e.value.message
    assert "harnesses.codex" in e.value.hint


def test_a_codex_entry_with_an_unset_required_variable_is_refused_before_a_worker_starts(tmp_path, monkeypatch):
    machine = CODEX_MACHINE.replace("${OPENAI_API_KEY}", "${OPENAI_API_KEY:?set OPENAI_API_KEY or run codex login}")
    monkeypatch.setenv("FACTORY_HOME", str(_home(tmp_path, machine)))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = load_config(_repo(tmp_path, "codex"))
    with pytest.raises(FactoryError) as e:
        api.default_workers(cfg)
    assert e.value.code == "config.invalid" and "set OPENAI_API_KEY or run codex login" in e.value.message


def test_a_repo_that_chooses_claude_still_gets_the_claude_adapter(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(_home(tmp_path, None)))
    cfg = load_config(_repo(tmp_path, "claude"))
    workers = api.default_workers(cfg)
    assert list(workers) == ["claude"] and isinstance(workers["claude"], ClaudeAdapter)
