"""Module 9 and P2-1 acceptance criteria for the Codex adapter, run against a stub `codex` that replays recorded JSONL.

The stub runs under the real `srt`, as the adapter always wraps it, so the stub tests need srt 0.0.83 and Node 22.12 or
later. Without them they skip, the same as the other srt tests. The sandbox tests use the real srt and the real
settings file, and make no model call.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from factory_engine.adapters.worker import codex as X
from factory_engine.adapters.worker import sandbox
from factory_engine.adapters.worker.codex import CodexAdapter
from factory_engine.errors import FactoryError
from factory_engine.types import HelperPolicy

from conftest import HERE, RECORDED, harness, log_seen_while_running

SRT = shutil.which("srt")
needs_srt = pytest.mark.skipif(SRT is None or sandbox.node_version() is None or sandbox.node_version()[:2] < (22, 12),
                               reason="srt 0.0.83 and Node 22.12+ are required (module 9)")

GATEWAY = "https://gw.example.test/v1"
GATEWAY_HOST = "gw.example.test"
ENV_KEY = {"OPENAI_API_KEY": "sk-gateway-SECRET-123", "OPENAI_BASE_URL": GATEWAY}
CONF = harness("codex", {"OPENAI_API_KEY": "${OPENAI_API_KEY}", "OPENAI_BASE_URL": "${OPENAI_BASE_URL}"})


class CodexStub:
    """One stub `codex` in bindir. Its record goes into the task folder, the one place srt lets a child write."""

    def __init__(self, bindir: Path, record: Path):
        self.record = record
        self.config_path = bindir / "stub_config.json"
        self.exe = bindir / "codex"
        self.exe.write_text(f"#!/bin/sh\nexec {sys.executable} -I {HERE / 'stub_codex.py'} {self.config_path} \"$@\"\n")
        self.exe.chmod(0o755)
        self.set(result=str(RECORDED / "codex" / "ok.jsonl"))

    def set(self, **cfg) -> "CodexStub":
        base = {"result": str(RECORDED / "codex" / "ok.jsonl"), "stderr": "", "exit": 0, "sleep": 0, "artifact": None,
                "helpers": 0, "record": str(self.record)}
        base.update(cfg)
        self.config_path.write_text(json.dumps(base))
        return self

    def seen(self, name: str) -> str:
        return (self.record / name).read_text()

    def argv(self) -> list[str]:
        return self.seen("argv.txt").splitlines()

    def env(self) -> dict:
        return json.loads(self.seen("env.json"))


@pytest.fixture
def stub(tmp_path, task_dir) -> CodexStub:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    return CodexStub(bindir, task_dir / "stub-record")


@pytest.fixture
def machine(stub, tmp_path) -> dict:
    # srt is a Node script that finds `node` on PATH, and the adapter passes its scrubbed environment to srt as well.
    node = shutil.which("node")
    node_dir = [str(Path(node).parent)] if node else []
    return {"PATH": ":".join([str(stub.exe.parent), *node_dir, "/usr/bin", "/bin"]), "HOME": str(tmp_path / "userhome")}


def gateway_adapter(machine, **extra):
    return CodexAdapter({**machine, **ENV_KEY, **extra})


def attempt(adapter, ctx, conf, tmp_path, timeout=60):
    log = tmp_path / "worker.log"
    handle = adapter.start(ctx, conf, log)
    return adapter.wait(handle, timeout), log


def conf_for(stub, env=None):
    return harness(str(stub.exe), env if env is not None else CONF.env)


def fixture(name: str) -> str:
    return str(RECORDED / "codex" / name)


def write_events(tmp_path: Path, name: str, events: list[dict]) -> str:
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return str(path)


# ---- the headless run and its environment -------------------------------------------------------------------------

@needs_srt
def test_the_worker_runs_headless_in_the_task_worktree(stub, machine, make_ctx, worktree, tmp_path):
    result, _ = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    assert result.exit == "ok"
    assert Path(stub.seen("cwd.txt").strip()).resolve() == worktree.resolve()
    argv = stub.argv()
    assert argv[argv.index("-C") + 1] == str(worktree)
    assert argv[:2] == ["exec", "--json"] and argv[-1] == "-"


@needs_srt
def test_the_prompt_reaches_the_worker_on_stdin(stub, machine, make_ctx, tmp_path):
    result, _ = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    assert result.exit == "ok"
    text = stub.seen("prompt.txt")
    assert "factory-fix" in text and "src/**" in text and "stage-report" in text


@needs_srt
def test_the_child_gets_only_the_declared_variables_and_the_folders_the_adapter_sets(stub, machine, make_ctx, task_dir,
                                                                                     tmp_path):
    leaks = {"SSH_AUTH_SOCK": "/tmp/agent.sock", "AWS_SECRET_ACCESS_KEY": "aws-SECRET"}
    adapter = CodexAdapter({**machine, **ENV_KEY, **leaks, "GH_TOKEN": "gh-SECRET"})
    result, _ = attempt(adapter, make_ctx(), conf_for(stub), tmp_path)
    assert result.exit == "ok"
    env = stub.env()
    assert env["OPENAI_API_KEY"] == ENV_KEY["OPENAI_API_KEY"]
    assert env["OPENAI_BASE_URL"] == GATEWAY
    assert env["FACTORY_TASK_DIR"] == str(task_dir)
    assert env["CODEX_HOME"] == str(task_dir / "codex-home")
    assert env["npm_config_cache"].startswith(str(task_dir))
    for name in leaks:
        assert name not in env, f"{name} leaked into the worker"
    assert "GH_TOKEN" not in env and "GITHUB_TOKEN" not in env


@needs_srt
def test_codex_home_is_an_empty_folder_with_no_login_file(stub, machine, make_ctx, tmp_path):
    result, _ = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    assert result.exit == "ok"
    assert json.loads(stub.seen("codex-home.txt")) == []


def test_a_harness_config_cannot_hand_a_worker_a_github_token(machine, tmp_path):
    with pytest.raises(FactoryError) as e:
        CodexAdapter(machine).child_env(harness("codex", {**ENV_KEY, "GITHUB_TOKEN": "gh-SECRET"}), tmp_path)
    assert e.value.code == "config.invalid"


@needs_srt
def test_the_base_url_defaults_to_the_public_api_when_the_machine_sets_none(stub, machine, make_ctx, tmp_path):
    # Untested live: every recorded run used the IBM gateway. This checks only the value the adapter sends.
    adapter = CodexAdapter({**machine, "OPENAI_API_KEY": "sk-x"})
    attempt(adapter, make_ctx(), conf_for(stub, {"OPENAI_API_KEY": "${OPENAI_API_KEY}"}), tmp_path)
    assert "model_providers.custom.base_url=https://api.openai.com/v1" in stub.argv()


# ---- the command line -------------------------------------------------------------------------------------------

@needs_srt
def test_the_provider_comes_from_per_key_overrides_and_the_sandbox_is_codex_full_access(stub, machine, make_ctx, tmp_path):
    attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    argv = stub.argv()
    overrides = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert f"model_providers.custom.base_url={GATEWAY}" in overrides
    assert "model_providers.custom.env_key=OPENAI_API_KEY" in overrides
    assert "model_providers.custom.wire_api=responses" in overrides
    assert all("{" not in o for o in overrides), "an inline table would not parse in codex"
    assert argv[argv.index("-s") + 1] == "danger-full-access"
    assert "--ignore-user-config" in argv and "--ephemeral" in argv


@needs_srt
def test_a_model_flag_appears_only_when_the_task_or_harness_sets_a_model(stub, machine, make_ctx, tmp_path):
    attempt(gateway_adapter(machine), make_ctx(model=None), conf_for(stub), tmp_path)
    assert "-m" not in stub.argv()
    attempt(gateway_adapter(machine), make_ctx(model="gpt-task"), conf_for(stub), tmp_path)
    argv = stub.argv()
    assert argv[argv.index("-m") + 1] == "gpt-task"
    attempt(gateway_adapter(machine), make_ctx(model=None), harness(str(stub.exe), CONF.env, model="gpt-harness"), tmp_path)
    argv = stub.argv()
    assert argv[argv.index("-m") + 1] == "gpt-harness"


@needs_srt
def test_multi_agent_is_switched_off_only_when_helpers_are_off(stub, machine, make_ctx, tmp_path):
    attempt(gateway_adapter(machine), make_ctx(helpers=HelperPolicy("off", 0, [], None)), conf_for(stub), tmp_path)
    argv = stub.argv()
    assert argv[argv.index("--disable") + 1] == "multi_agent"
    attempt(gateway_adapter(machine), make_ctx(helpers=HelperPolicy("auto", 2, ["api", "tests"], 10)), conf_for(stub), tmp_path)
    assert "--disable" not in stub.argv()


# ---- tokens, models and the artifact -----------------------------------------------------------------------------

@needs_srt
def test_tokens_come_from_the_last_turn_completed_usage(stub, machine, make_ctx, tmp_path):
    result, _ = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    assert (result.input_tokens, result.output_tokens) == (24928, 51)


@needs_srt
def test_tokens_are_null_when_no_usage_is_reported(stub, machine, make_ctx, tmp_path):
    stub.set(result=fixture("no-usage.jsonl"))
    result, _ = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    assert result.exit == "ok"
    assert (result.input_tokens, result.output_tokens) == (None, None)


@needs_srt
def test_a_count_the_usage_event_omits_stays_null_and_is_never_zero(stub, machine, make_ctx, tmp_path):
    events = [{"type": "turn.started"}, {"type": "turn.completed", "usage": {"input_tokens": 7}}]
    stub.set(result=write_events(tmp_path, "partial-usage.jsonl", events))
    result, _ = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    assert (result.input_tokens, result.output_tokens) == (7, None)


@needs_srt
def test_models_observed_is_empty_because_codex_reports_no_model_name(stub, machine, make_ctx, tmp_path):
    result, _ = attempt(gateway_adapter(machine), make_ctx(model="gpt-task"), conf_for(stub), tmp_path)
    assert result.models_observed == []


@needs_srt
def test_the_artifact_the_task_names_is_returned_when_the_worker_wrote_it(stub, machine, make_ctx, task_dir, tmp_path):
    stub.set(artifact=["stage.json", '{"ok": true}'])
    result, _ = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    assert result.artifact == task_dir / "stage.json"


# ---- failure kinds ------------------------------------------------------------------------------------------------

@needs_srt
def test_a_401_is_auth_and_needs_a_human(stub, machine, make_ctx, tmp_path):
    stub.set(result=fixture("noauth.jsonl"), exit=1)
    result, _ = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    assert (result.exit, result.error_kind) == ("failed", "auth")


@needs_srt
def test_a_403_for_the_model_is_model_not_found(stub, machine, make_ctx, tmp_path):
    stub.set(result=fixture("nomodel.jsonl"), exit=1)
    result, _ = attempt(gateway_adapter(machine), make_ctx(model="gpt-5-codex"), conf_for(stub), tmp_path)
    assert (result.exit, result.error_kind) == ("failed", "model_not_found")


@needs_srt
def test_a_429_is_rate_limit(stub, machine, make_ctx, tmp_path):
    events = [{"type": "thread.started", "thread_id": "x"}, {"type": "turn.started"},
              {"type": "error", "message": "Reconnecting... 1/5 (unexpected status 429 Too Many Requests: rate limit)"},
              {"type": "turn.failed", "error": {"message": "unexpected status 429 Too Many Requests"}}]
    stub.set(result=write_events(tmp_path, "rate.jsonl", events), exit=1)
    result, _ = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    assert (result.exit, result.error_kind) == ("failed", "rate_limit")


@needs_srt
def test_any_other_failure_is_a_crash(stub, machine, make_ctx, tmp_path):
    events = [{"type": "turn.started"},
              {"type": "turn.failed", "error": {"message": "stream disconnected before completion"}}]
    stub.set(result=write_events(tmp_path, "crash.jsonl", events), exit=1)
    result, _ = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    assert (result.exit, result.error_kind) == ("failed", "crash")


@needs_srt
def test_a_nonzero_exit_with_a_completed_turn_is_a_crash(stub, machine, make_ctx, tmp_path):
    stub.set(result=fixture("ok.jsonl"), exit=3)
    result, _ = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    assert (result.exit, result.error_kind) == ("failed", "crash")


@needs_srt
def test_a_missing_binary_is_binary_missing(machine, make_ctx, tmp_path):
    adapter = gateway_adapter(machine)
    result, _ = attempt(adapter, make_ctx(), harness(str(tmp_path / "no-such-codex"), CONF.env), tmp_path)
    assert (result.exit, result.error_kind) == ("failed", "binary_missing")


@needs_srt
def test_a_timeout_kills_the_worker_and_is_reported(stub, machine, make_ctx, tmp_path):
    stub.set(sleep=30)
    result, _ = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path, timeout=1)
    assert result.exit == "timeout"


# ---- the log and secrets ------------------------------------------------------------------------------------------

@needs_srt
def test_the_worker_log_is_plain_text_and_masks_the_key(stub, machine, make_ctx, tmp_path):
    stub.set(stderr=f"debug: key was {ENV_KEY['OPENAI_API_KEY']}")
    _, log = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    text = log.read_text()
    assert ENV_KEY["OPENAI_API_KEY"] not in text
    assert "***" in text
    assert "done" in text and "$ /bin/zsh" in text  # the agent message and the command line, as plain text
    assert not text.lstrip().startswith("{")


def test_worker_log_has_the_agent_text_while_the_worker_is_still_running(stub, machine, make_ctx, tmp_path):
    stub.set(early_out='{"type": "item.completed", "item": {"type": "agent_message", "text": "reading the failing test"}}', sleep=60)
    adapter, log = gateway_adapter(machine), tmp_path / "worker.log"
    handle = adapter.start(make_ctx(), conf_for(stub), log)
    seen, running = log_seen_while_running(adapter, handle, log, "reading the failing test")
    assert seen and running
    assert not log.read_text().lstrip().startswith("{")  # plain text, not the event line


# ---- stop -----------------------------------------------------------------------------------------------------

@needs_srt
def test_stop_ends_the_worker_and_its_helper_sessions(stub, machine, make_ctx, tmp_path):
    stub.set(helpers=2, sleep=60)
    adapter = gateway_adapter(machine)
    handle = adapter.start(make_ctx(helpers=HelperPolicy("auto", 2, [], 10)), conf_for(stub), tmp_path / "worker.log")
    pids_file = stub.record / "helper-pids.txt"
    for _ in range(400):
        if pids_file.is_file():
            break
        time.sleep(0.05)
    helpers = [int(x) for x in pids_file.read_text().split()]
    assert helpers, "the stub did not start its helper sessions"
    adapter.stop(handle)
    result = adapter.wait(handle, 5)
    assert result.exit == "killed"
    for pid in helpers:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


# ---- the settings file and sandbox refusals ----------------------------------------------------------------------

def test_a_settings_file_that_is_not_json_stops_the_attempt_before_the_worker_starts(tmp_path):
    bad = tmp_path / "srt-settings.json"
    bad.write_text("{not json")
    with pytest.raises(FactoryError) as e:
        X.parse_settings_file(bad)
    assert e.value.code == "sandbox.settings_unparseable"


def test_a_settings_field_of_the_wrong_type_is_refused_before_the_worker_starts(tmp_path):
    bad = tmp_path / "srt-settings.json"
    bad.write_text(json.dumps({"filesystem": {"denyRead": "/x", "allowRead": [], "allowWrite": [], "denyWrite": []},
                               "network": {"allowedDomains": [], "deniedDomains": []}}))
    with pytest.raises(FactoryError) as e:
        X.parse_settings_file(bad)
    assert e.value.code == "sandbox.settings_invalid"


def test_the_settings_allow_only_the_gateway_host_and_grant_the_codex_mach_lookup(worktree, task_dir, factory_home):
    doc = X.srt_settings(worktree, task_dir, GATEWAY, factory_home)
    assert doc["network"]["allowedDomains"] == [GATEWAY_HOST]
    assert doc["network"]["allowMachLookup"] == ["com.apple.trustd.agent"]
    assert str(factory_home.resolve()) in doc["filesystem"]["denyRead"]


@needs_srt
def test_the_worker_is_confined_by_srt_and_cannot_write_outside_its_folders(stub, machine, make_ctx, worktree, tmp_path):
    inside, outside = worktree / "in.txt", tmp_path / "outside.txt"
    stub.set(writes=[str(inside), str(outside)])
    result, _ = attempt(gateway_adapter(machine), make_ctx(), conf_for(stub), tmp_path)
    assert result.exit == "ok"
    assert json.loads(stub.seen("writes.json")) == {str(inside): "written", str(outside): "refused"}
    assert inside.exists() and not outside.exists()


def test_a_missing_srt_refuses_the_worker_before_it_runs(stub, machine, make_ctx, tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))  # srt is looked up on the process PATH
    adapter = CodexAdapter({**machine, **ENV_KEY, "PATH": str(empty)})
    with pytest.raises(FactoryError) as e:
        adapter.start(make_ctx(), conf_for(stub), tmp_path / "worker.log")
    assert e.value.code == "sandbox.srt_missing"
    assert not (stub.record / "argv.txt").exists()


# ---- doctor -------------------------------------------------------------------------------------------------------

def test_doctor_fails_with_no_key_and_names_the_variable_not_a_value(stub, machine):
    check = CodexAdapter(machine).check(conf_for(stub, {}))
    assert check.ok is False
    assert "config.no_credentials" in check.detail and "OPENAI_API_KEY" in check.detail


@needs_srt
def test_doctor_passes_with_a_key_and_never_prints_its_value(stub, machine):
    check = gateway_adapter(machine).check(conf_for(stub))
    assert check.ok is True
    assert ENV_KEY["OPENAI_API_KEY"] not in check.detail and ENV_KEY["OPENAI_API_KEY"] not in check.hint


def test_doctor_fails_when_the_codex_binary_is_missing(machine, tmp_path):
    check = gateway_adapter(machine).check(harness(str(tmp_path / "absent-codex"), CONF.env))
    assert check.ok is False and "not found" in check.detail


# ---- the srt settings the adapter writes, against the real srt ------------------------------------------------

@pytest.fixture
def codex_home_user(tmp_path, monkeypatch):
    """A user home with a Codex key file, so the deny rule for ~/.codex is exercised against a real file."""
    home = tmp_path / "userhome"
    (home / ".codex").mkdir(parents=True)
    key = home / ".codex" / "auth.json"
    key.write_text('{"OPENAI_API_KEY": "sk-auth-SECRET"}')
    monkeypatch.setenv("HOME", str(home))
    return key


def probe(settings: Path, worktree: Path, argv: list[str]) -> int:
    """Runs one command under srt with the given settings, the way the adapter wraps a worker."""
    cmd = sandbox.srt_command(SRT, settings, argv)
    return subprocess.run(cmd, cwd=worktree, capture_output=True, text=True).returncode


def write_settings(tmp_path: Path, worktree: Path, task_dir: Path, factory: Path) -> Path:
    path = tmp_path / "srt-settings.json"
    path.write_text(X.render_settings(worktree, task_dir, GATEWAY, factory))
    return path


@needs_srt
def test_the_codex_settings_block_reads_of_the_factory_home_and_the_codex_key_file(worktree, task_dir, factory_home,
                                                                                    codex_home_user, tmp_path):
    secret = factory_home / "config.yaml"
    secret.write_text("secret: value\n")
    settings = write_settings(tmp_path, worktree, task_dir, factory_home)
    py = [sys.executable, "-c", f"open({str(secret)!r}).read()"]
    assert probe(settings, worktree, ["cat", str(secret)]) != 0
    assert probe(settings, worktree, py) != 0
    assert probe(settings, worktree, ["cat", str(codex_home_user)]) != 0
    assert probe(settings, worktree, [sys.executable, "-c", f"open({str(codex_home_user)!r}).read()"]) != 0


@needs_srt
def test_the_codex_settings_allow_writes_in_the_worktree_and_task_folder_and_refuse_outside_both(worktree, task_dir,
                                                                                               factory_home, tmp_path):
    settings = write_settings(tmp_path, worktree, task_dir, factory_home)
    inside, in_task, outside = worktree / "a.txt", task_dir / "b.txt", tmp_path / "outside.txt"
    assert probe(settings, worktree, ["sh", "-c", f"echo a > {inside}"]) == 0
    assert probe(settings, worktree, ["sh", "-c", f"echo b > {in_task}"]) == 0
    assert probe(settings, worktree, ["sh", "-c", f"echo c > {outside}"]) != 0
    assert inside.exists() and in_task.exists() and not outside.exists()
