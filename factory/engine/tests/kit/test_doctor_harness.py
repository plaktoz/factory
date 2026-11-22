"""D2 (owner decision 2026-11-22): `factory doctor` runs the module 9 sandbox canary and the Claude canary and probe on
every run. The paid checks run only when the binary and credentials check passes, since a call without them can only fail."""

from factory_engine import api
from factory_engine.adapters.worker import claude as claude_mod
from factory_engine.adapters.worker import sandbox
from factory_engine.adapters.worker.claude import ClaudeAdapter
from factory_engine.types import CheckResult


def _fake_world(monkeypatch, tmp_path, *, srt=True, claude=True):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    calls = []
    monkeypatch.setattr(sandbox, "check_srt", lambda: CheckResult("srt", srt, "srt", "install srt"))
    monkeypatch.setattr(sandbox, "canary_srt", lambda wt, td, home: calls.append("srt canary") or CheckResult("srt canary", True, "", ""))
    monkeypatch.setattr(ClaudeAdapter, "check", lambda self, conf: CheckResult("claude", claude, "claude", "fix claude"))
    monkeypatch.setattr(claude_mod, "canary_claude", lambda conf, **kw: calls.append("claude canary") or CheckResult("claude canary", True, "", ""))
    monkeypatch.setattr(claude_mod, "probe_isolation", lambda conf, wt, td, **kw: calls.append("probe") or CheckResult("worker isolation", True, "", ""))
    return calls


def test_a_healthy_machine_runs_the_sandbox_canary_the_claude_canary_and_the_probe(monkeypatch, tmp_path):
    calls = _fake_world(monkeypatch, tmp_path)
    names = [c.name for c in api._harness_checks(False)]
    assert names == ["srt", "srt canary", "claude", "claude canary", "worker isolation"]
    assert calls == ["srt canary", "claude canary", "probe"]


def test_no_model_call_is_made_when_the_claude_binary_or_credentials_check_fails(monkeypatch, tmp_path):
    calls = _fake_world(monkeypatch, tmp_path, claude=False)
    checks = api._harness_checks(False)
    assert [c.name for c in checks] == ["srt", "srt canary", "claude"] and not checks[-1].ok
    assert "claude canary" not in calls and "probe" not in calls


def test_a_missing_srt_skips_its_canary_and_still_reports_it(monkeypatch, tmp_path):
    calls = _fake_world(monkeypatch, tmp_path, srt=False)
    checks = api._harness_checks(False)
    assert not checks[0].ok and "srt canary" not in calls


def test_doctor_includes_the_harness_checks_and_fails_when_one_does(repo_with_config, monkeypatch, tmp_path):
    calls = _fake_world(monkeypatch, tmp_path)
    monkeypatch.setattr(claude_mod, "canary_claude", lambda conf, **kw: CheckResult("claude canary", False, "sandbox.canary_open: read via cat", "fix"))
    by = {c.name: c for c in api.doctor(repo_with_config)}
    assert not by["claude canary"].ok and "read via cat" in by["claude canary"].detail
    assert "worker isolation" in by                      # a failing canary does not hide the rest


def test_as_scheduler_gives_the_claude_checks_the_short_cron_environment(monkeypatch, tmp_path):
    seen = {}
    _fake_world(monkeypatch, tmp_path)
    monkeypatch.setattr(claude_mod, "canary_claude", lambda conf, environ=None, **kw: seen.update(env=environ) or CheckResult("claude canary", True, "", ""))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    api._harness_checks(True)
    assert seen["env"] == {"PATH": "/usr/bin:/bin", "HOME": seen["env"]["HOME"]} and "ANTHROPIC_API_KEY" not in seen["env"]


import subprocess

import pytest


@pytest.fixture
def repo_with_config(tmp_path):
    from factory_engine import kit
    r = tmp_path / "repo"
    (r / ".factory" / "config").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (r / ".factory" / "config" / "factory.yaml").write_text("base_branch: main\n")
    return r


def test_an_unset_required_variable_in_the_harness_env_is_a_failed_check_not_a_crash(monkeypatch, tmp_path):
    """`${VAR:?message}` in the machine file's harness env raises; doctor must report it and keep its other checks."""
    calls = _fake_world(monkeypatch, tmp_path)
    monkeypatch.undo()                                   # use the real ClaudeAdapter.check and config loader
    home = tmp_path / "home2"
    home.mkdir()
    (home / "config.yaml").write_text("harnesses:\n  claude:\n    command: claude\n    env:\n      ANTHROPIC_API_KEY: ${NO_SUCH_KEY_VAR:?set the key}\n")
    monkeypatch.setenv("FACTORY_HOME", str(home))
    monkeypatch.delenv("NO_SUCH_KEY_VAR", raising=False)
    monkeypatch.setattr(sandbox, "check_srt", lambda: CheckResult("srt", False, "srt missing", "install srt"))
    checks = api._harness_checks(False)
    assert [c.name for c in checks] == ["srt", "claude"]
    assert not checks[-1].ok and "set the key" in checks[-1].detail
