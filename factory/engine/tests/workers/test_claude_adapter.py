"""Module 9 acceptance criteria for the Claude adapter, run against the stub `claude` that replays recorded JSON."""

import json
import os
import time
from pathlib import Path

import pytest

from factory_engine.adapters.worker import claude as C
from factory_engine.adapters.worker.claude import ClaudeAdapter
from factory_engine.errors import FactoryError
from factory_engine.types import HelperPolicy, McpServer

from conftest import ENV_GW, RECORDED, harness


def attempt(adapter, ctx, conf, tmp_path, timeout=60):
    """One attempt through the adapter's own start and wait. Returns (AttemptResult, worker.log path)."""
    log = tmp_path / "worker.log"
    handle = adapter.start(ctx, conf, log)
    return adapter.wait(handle, timeout), log


def gateway_adapter(machine, **extra):
    return ClaudeAdapter({**machine, **ENV_GW, **extra})


GW_CONF = harness("claude", {k: f"${{{k}}}" for k in ENV_GW} | {"ANTHROPIC_BASE_URL": ENV_GW["ANTHROPIC_BASE_URL"]})


# ---- the headless run and its environment ---------------------------------------------------------------------------

def test_the_worker_runs_headless_in_the_task_worktree(stub, machine, make_ctx, worktree, tmp_path):
    stub.set(result=str(RECORDED / "ok.json"))
    result, _ = attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path)
    assert result.exit == "ok"
    assert Path(stub.seen("cwd.txt").strip()).resolve() == worktree.resolve()
    assert stub.argv()[:2] == ["-p", "--output-format"]


def test_the_child_gets_only_the_declared_variables_and_the_task_dir(stub, machine, make_ctx, task_dir, tmp_path):
    secrets = {"SSH_AUTH_SOCK": "/tmp/agent.sock", "AWS_SECRET_ACCESS_KEY": "aws-SECRET", "OPENAI_API_KEY": "oai-SECRET"}
    adapter = ClaudeAdapter({**machine, **ENV_GW, **secrets})
    result, _ = attempt(adapter, make_ctx(), GW_CONF, tmp_path)
    assert result.exit == "ok"
    env = stub.env()
    assert env["FACTORY_TASK_DIR"] == str(task_dir)
    assert env["ANTHROPIC_AUTH_TOKEN"] == ENV_GW["ANTHROPIC_AUTH_TOKEN"]
    for name in secrets:
        assert name not in env, f"{name} leaked into the worker"
    assert "GH_TOKEN" not in env


def test_a_harness_config_cannot_hand_a_worker_a_github_token(machine, tmp_path):
    with pytest.raises(FactoryError) as e:
        ClaudeAdapter(machine).child_env(harness("claude", {**ENV_GW, "GH_TOKEN": "gh-SECRET"}), tmp_path)
    assert e.value.code == "config.invalid"


# ---- the prompt ------------------------------------------------------------------------------------------------------

def test_the_prompt_carries_the_skill_scope_helpers_feedback_notes_and_schema(stub, machine, make_ctx, tmp_path):
    feedback = tmp_path / "f1.json"
    feedback.write_text('{"gate": "scope-diff", "reason": "touched secrets/key"}')
    ctx = make_ctx(helpers=HelperPolicy("auto", 2, ["api-code", "tests"], 15))
    ctx.feedback = [feedback]
    ctx.notes = ["Keep the public signature"]
    result, _ = attempt(gateway_adapter(machine), ctx, GW_CONF, tmp_path)
    assert result.exit == "ok"
    text = stub.seen("prompt.txt")
    assert "factory-fix" in text                       # the skill reference
    assert "src/**" in text and "secrets/**" in text   # scope and deny paths
    assert "at most 2 helpers" in text                 # the helper policy in plain words
    assert "api-code, tests" in text                   # its split hints
    assert "touched secrets/key" in text               # the feedback record
    assert "Keep the public signature" in text         # the delivered note
    assert "stage-report" in text                      # the output schema


def test_a_practice_pack_appears_as_a_path_and_one_line_never_its_text(stub, machine, make_ctx, tmp_path):
    from factory_engine.skills import SkillRef
    pack = tmp_path / "packs" / "java"
    pack.mkdir(parents=True)
    (pack / "SKILL.md").write_text("---\nname: java\ndescription: Java style rules for Maven projects.\n---\n"
                                   "PACK_BODY_MUST_NOT_APPEAR\n")
    ctx = make_ctx()
    ctx.practices = [SkillRef("java", "own", pack, {})]
    result, _ = attempt(gateway_adapter(machine), ctx, GW_CONF, tmp_path)
    assert result.exit == "ok"
    text = stub.seen("prompt.txt")
    assert str(pack / "SKILL.md") in text and "Java style rules for Maven projects." in text
    assert "PACK_BODY_MUST_NOT_APPEAR" not in text


# ---- tokens and models from the recorded result -------------------------------------------------------------------

def test_tokens_are_parsed_from_the_result(stub, machine, make_ctx, tmp_path):
    result, _ = attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path)
    assert (result.input_tokens, result.output_tokens) == (2, 4)


def test_tokens_are_null_when_the_result_reports_none(stub, machine, make_ctx, tmp_path):
    stub.set(result=str(RECORDED / "no-usage.json"))
    result, _ = attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path)
    assert (result.input_tokens, result.output_tokens) == (None, None)
    assert result.models_observed == []


def test_with_no_model_in_config_the_command_has_no_model_flag_and_models_come_from_modelusage(stub, machine, make_ctx, tmp_path):
    result, _ = attempt(gateway_adapter(machine), make_ctx(model=None), GW_CONF, tmp_path)
    assert result.exit == "ok"
    assert "--model" not in stub.argv()
    assert result.models_observed == ["claude-advantage-assist"]


def test_a_result_with_two_modelusage_keys_gives_both_names_and_summed_tokens(stub, machine, make_ctx, tmp_path):
    stub.set(result=str(RECORDED / "two-models.json"))
    result, _ = attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path)
    assert result.models_observed == ["claude-advantage-assist", "claude-helper-model"]
    assert (result.input_tokens, result.output_tokens) == (15, 6)


# ---- the model flag and ANTHROPIC_MODEL ---------------------------------------------------------------------------

def test_a_model_flag_from_the_task_wins_over_anthropic_model(stub, machine, make_ctx, tmp_path):
    adapter = gateway_adapter(machine, ANTHROPIC_MODEL="machine-model")
    conf = harness("claude", {**ENV_GW, "ANTHROPIC_MODEL": "${ANTHROPIC_MODEL:-}"})
    attempt(adapter, make_ctx(model="task-model"), conf, tmp_path)
    argv = stub.argv()
    assert argv[argv.index("--model") + 1] == "task-model"


def test_anthropic_model_from_the_machine_reaches_a_scrubbed_worker_with_no_flag(stub, machine, make_ctx, tmp_path):
    adapter = gateway_adapter(machine, ANTHROPIC_MODEL="claude-advantage-assist")
    result, _ = attempt(adapter, make_ctx(model=None), GW_CONF, tmp_path)
    assert result.exit == "ok"
    assert stub.env()["ANTHROPIC_MODEL"] == "claude-advantage-assist"


def test_without_anthropic_model_the_worker_ends_as_model_not_found_and_needs_a_human(stub, machine, make_ctx, tmp_path):
    stub.set(result=str(RECORDED / "nomodel.json"))
    result, _ = attempt(gateway_adapter(machine), make_ctx(model=None), GW_CONF, tmp_path)
    assert (result.exit, result.error_kind) == ("failed", "model_not_found")
    assert "ANTHROPIC_MODEL" not in stub.env()


def test_an_empty_anthropic_model_is_passed_as_unset(stub, machine, make_ctx, tmp_path):
    stub.set(result=str(RECORDED / "nomodel.json"))
    adapter = gateway_adapter(machine, ANTHROPIC_MODEL="")
    result, _ = attempt(adapter, make_ctx(model=None), GW_CONF, tmp_path)
    assert "ANTHROPIC_MODEL" not in stub.env()
    assert result.error_kind == "model_not_found"


# ---- the base URL and the auth failure ----------------------------------------------------------------------------

def test_the_base_url_reaches_the_worker_from_the_machine_when_the_config_does_not_declare_it(stub, machine, make_ctx, tmp_path):
    adapter = ClaudeAdapter({**machine, **ENV_GW})
    conf = harness("claude", {"ANTHROPIC_AUTH_TOKEN": ENV_GW["ANTHROPIC_AUTH_TOKEN"]})
    result, _ = attempt(adapter, make_ctx(), conf, tmp_path)
    assert result.exit == "ok"
    assert stub.env()["ANTHROPIC_BASE_URL"] == ENV_GW["ANTHROPIC_BASE_URL"]


def test_a_missing_base_url_ends_as_auth_and_needs_a_human(stub, machine, make_ctx, tmp_path):
    stub.set(result=str(RECORDED / "noauth.json"))
    adapter = ClaudeAdapter({**machine, "ANTHROPIC_AUTH_TOKEN": ENV_GW["ANTHROPIC_AUTH_TOKEN"]})
    result, _ = attempt(adapter, make_ctx(), harness("claude", {"ANTHROPIC_AUTH_TOKEN": ENV_GW["ANTHROPIC_AUTH_TOKEN"]}), tmp_path)
    assert (result.exit, result.error_kind) == ("failed", "auth")
    assert "ANTHROPIC_BASE_URL" not in stub.env()


def test_an_empty_base_url_ends_as_auth(stub, machine, make_ctx, tmp_path):
    stub.set(result=str(RECORDED / "noauth.json"))
    adapter = ClaudeAdapter({**machine, "ANTHROPIC_AUTH_TOKEN": ENV_GW["ANTHROPIC_AUTH_TOKEN"], "ANTHROPIC_BASE_URL": ""})
    result, _ = attempt(adapter, make_ctx(), harness("claude", {"ANTHROPIC_AUTH_TOKEN": ENV_GW["ANTHROPIC_AUTH_TOKEN"]}), tmp_path)
    assert result.error_kind == "auth"


# ---- the log and secrets ------------------------------------------------------------------------------------------

def test_secret_values_never_appear_in_the_worker_log(stub, machine, make_ctx, tmp_path):
    stub.set(stderr=f"debug: token was {ENV_GW['ANTHROPIC_AUTH_TOKEN']}")
    _, log = attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path)
    text = log.read_text()
    assert ENV_GW["ANTHROPIC_AUTH_TOKEN"] not in text
    assert "***" in text


# ---- the sandbox settings file ------------------------------------------------------------------------------------

def test_every_attempt_has_a_settings_file_with_the_required_sandbox_rules(stub, machine, make_ctx, worktree, task_dir,
                                                                           tmp_path, factory_home):
    result, _ = attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path)
    assert result.exit == "ok"
    sb = json.loads(stub.seen("settings.json"))["sandbox"]
    assert sb["enabled"] is True and sb["failIfUnavailable"] is True and sb["allowUnsandboxedCommands"] is False
    fs = sb["filesystem"]
    assert str(factory_home.resolve()) in fs["denyRead"]
    for credential in ("~/.ssh", "~/.aws", "~/.config/gh", "~/.codex"):
        assert str(Path(credential).expanduser().resolve()) in fs["denyRead"]
    assert str(task_dir.resolve()) in fs["allowRead"]
    assert set(fs["allowWrite"]) == {str(worktree.resolve()), str(task_dir.resolve())}


def test_the_settings_file_and_mcp_config_are_deleted_when_the_attempt_ends(stub, machine, make_ctx, tmp_path, factory_home):
    attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path)
    assert (stub.record / "settings.json").is_file()  # the stub copied it while the worker ran
    tmp = factory_home / "tmp"
    assert not tmp.exists() or list(tmp.iterdir()) == []


def test_a_settings_file_that_is_not_json_stops_the_attempt_before_the_worker_starts(tmp_path):
    bad = tmp_path / "settings.json"
    bad.write_text("{not json")
    with pytest.raises(FactoryError) as e:
        C.parse_settings_file(bad)
    assert e.value.code == "sandbox.settings_unparseable"


def test_a_settings_field_of_the_wrong_type_is_refused_before_the_worker_starts(tmp_path):
    bad = tmp_path / "settings.json"
    bad.write_text(json.dumps({"sandbox": {"enabled": True, "failIfUnavailable": True,
                                           "filesystem": {"denyRead": "/x", "allowRead": [], "allowWrite": []}}}))
    with pytest.raises(FactoryError) as e:
        C.parse_settings_file(bad)
    assert e.value.code == "sandbox.settings_invalid"


def test_a_missing_settings_file_is_refused(tmp_path):
    with pytest.raises(FactoryError) as e:
        C.parse_settings_file(tmp_path / "absent.json")
    assert e.value.code == "sandbox.settings_unreadable"


def test_a_sandbox_that_cannot_start_fails_the_attempt_and_is_not_run_unsandboxed(stub, machine, make_ctx, tmp_path):
    stub.set(stderr="sandbox_apply: Operation not permitted", exit=71)
    with pytest.raises(FactoryError) as e:
        attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path)
    assert e.value.code == "sandbox.unavailable"


def test_a_settings_field_refused_by_claude_is_sandbox_settings_invalid(stub, machine, make_ctx, tmp_path):
    stub.set(stderr="sandbox required but unavailable: settings failed validation", exit=1)
    with pytest.raises(FactoryError) as e:
        attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path)
    assert e.value.code == "sandbox.settings_invalid"


def test_a_missing_settings_file_reported_by_claude_is_sandbox_settings_unreadable(stub, machine, make_ctx, tmp_path):
    stub.set(stderr="Settings file not found: /x/settings.json", exit=1)
    with pytest.raises(FactoryError) as e:
        attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path)
    assert e.value.code == "sandbox.settings_unreadable"


def test_sandbox_refusal_text_in_the_workers_own_answer_is_not_a_sandbox_failure(stub, machine, make_ctx, tmp_path):
    quoted = tmp_path / "quoted.json"
    quoted.write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                                  "result": "sandbox_apply: Operation not permitted",
                                  "modelUsage": {"claude-advantage-assist": {"inputTokens": 1, "outputTokens": 1}}}))
    stub.set(result=str(quoted))
    result, _ = attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path)
    assert result.exit == "ok"


# ---- read rules ---------------------------------------------------------------------------------------------------

def test_the_read_rules_deny_each_denied_file_and_not_the_task_folder(tmp_path):
    home = tmp_path / "factory"
    work = home / "runs" / "r1" / "tasks" / "backend" / "work"
    work.mkdir(parents=True)
    (home / "config.yaml").write_text("x")
    (home / "runs" / "r1" / "run.json").write_text("{}")
    rules = C.read_rules([str(home)], [str(work)])
    assert f"Read(//{str(home / 'config.yaml').lstrip('/')})" in rules
    assert f"Read(//{str(home / 'runs' / 'r1' / 'run.json').lstrip('/')})" in rules
    assert not any(str(work).lstrip("/") in r for r in rules)


def test_a_denied_folder_with_no_allowed_child_is_one_rule(tmp_path):
    ssh = tmp_path / "ssh"
    ssh.mkdir()
    (ssh / "id_rsa").write_text("key")
    assert C.read_rules([str(ssh)], [str(tmp_path / "unrelated")]) == [f"Read(//{str(ssh).lstrip('/')})"]


# ---- tool allow list, helpers and MCP -----------------------------------------------------------------------------

def test_bash_is_granted_per_command_and_never_as_a_bare_bash(stub, machine, make_ctx, tmp_path):
    attempt(gateway_adapter(machine), make_ctx(bash=["npm", "make"]), GW_CONF, tmp_path)
    argv = stub.argv()
    allowed = argv[argv.index("--allowedTools") + 1:]
    assert "Bash(npm:*)" in allowed and "Bash(make:*)" in allowed
    assert "Bash" not in allowed
    assert not any(a.startswith("Bash(python") for a in allowed)


def test_a_helper_off_task_loses_the_subagent_tools(stub, machine, make_ctx, tmp_path):
    attempt(gateway_adapter(machine), make_ctx(helpers=HelperPolicy("off", 0, [], None)), GW_CONF, tmp_path)
    argv = stub.argv()
    assert argv[argv.index("--disallowedTools") + 1] == "Agent"


def test_the_mcp_config_holds_only_the_servers_the_task_is_given(stub, machine, make_ctx, tmp_path):
    adapter = gateway_adapter(machine, TAVILY_API_KEY="tvly-SECRET")
    servers = [McpServer("tavily", "https://mcp.tavily.com/mcp/", None, {"Authorization": "Bearer ${TAVILY_API_KEY}"}, {})]
    attempt(adapter, make_ctx(mcp=servers), harness("claude", {**ENV_GW, "TAVILY_API_KEY": "${TAVILY_API_KEY}"}), tmp_path)
    doc = json.loads(stub.seen("mcp.json"))
    assert list(doc["mcpServers"]) == ["tavily"]
    assert doc["mcpServers"]["tavily"]["headers"]["Authorization"] == "Bearer tvly-SECRET"


def test_a_task_with_no_mcp_gets_an_empty_server_list(stub, machine, make_ctx, tmp_path):
    attempt(gateway_adapter(machine), make_ctx(mcp=[]), GW_CONF, tmp_path)
    assert json.loads(stub.seen("mcp.json")) == {"mcpServers": {}}


# ---- isolation flags ----------------------------------------------------------------------------------------------

def test_the_isolation_flags_are_passed(stub, machine, make_ctx, tmp_path):
    attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path)
    argv = stub.argv()
    assert argv[argv.index("--setting-sources") + 1] == "project"
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"


def test_the_output_format_from_config_args_is_not_duplicated(stub, machine, make_ctx, tmp_path):
    conf = harness("claude", GW_CONF.env, args=["--output-format", "json"])
    attempt(gateway_adapter(machine), make_ctx(), conf, tmp_path)
    assert stub.argv().count("--output-format") == 1


# ---- failure kinds, timeout and stop ------------------------------------------------------------------------------

def test_a_rate_limit_is_its_own_error_kind(stub, machine, make_ctx, tmp_path):
    rate = tmp_path / "rate.json"
    rate.write_text(json.dumps({"type": "result", "is_error": True, "api_error_status": 429,
                                "result": "rate limit reached", "modelUsage": {}}))
    stub.set(result=str(rate))
    result, _ = attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path)
    assert (result.exit, result.error_kind) == ("failed", "rate_limit")


def test_a_timeout_kills_the_worker_and_is_reported(stub, machine, make_ctx, tmp_path):
    stub.set(sleep=30)
    result, _ = attempt(gateway_adapter(machine), make_ctx(), GW_CONF, tmp_path, timeout=1)
    assert result.exit == "timeout"


def test_a_missing_binary_is_binary_missing(machine, make_ctx, tmp_path):
    result, _ = attempt(gateway_adapter(machine), make_ctx(), harness(str(tmp_path / "no-such-claude"), ENV_GW), tmp_path)
    assert (result.exit, result.error_kind) == ("failed", "binary_missing")


def test_doctor_fails_with_no_credentials_and_names_the_variables(stub, machine):
    adapter = ClaudeAdapter(machine)  # no key, no token
    check = adapter.check(harness(str(stub.exe), {}))
    assert check.ok is False
    assert "config.no_credentials" in check.detail and "ANTHROPIC_API_KEY" in check.detail


def test_doctor_passes_with_a_key_and_never_prints_its_value(stub, machine):
    key = "sk-ant-SECRET-VALUE-xyz"
    adapter = ClaudeAdapter({**machine, "ANTHROPIC_API_KEY": key})
    check = adapter.check(harness(str(stub.exe), {"ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"}))
    assert check.ok is True
    assert key not in check.detail and key not in check.hint


def test_doctor_passes_with_a_gateway_token_and_base_url_and_never_prints_the_token(stub, machine):
    check = gateway_adapter(machine).check(harness(str(stub.exe), GW_CONF.env))
    assert check.ok is True
    assert ENV_GW["ANTHROPIC_AUTH_TOKEN"] not in check.detail


def test_doctor_fails_when_the_claude_binary_is_missing(machine, tmp_path):
    check = gateway_adapter(machine).check(harness(str(tmp_path / "absent-claude"), GW_CONF.env))
    assert check.ok is False and "not found" in check.detail


def test_a_gateway_token_without_a_base_url_says_it_will_not_log_in(stub, machine):
    adapter = ClaudeAdapter({**machine, "ANTHROPIC_AUTH_TOKEN": ENV_GW["ANTHROPIC_AUTH_TOKEN"]})
    check = adapter.check(harness(str(stub.exe), {"ANTHROPIC_AUTH_TOKEN": ENV_GW["ANTHROPIC_AUTH_TOKEN"]}))
    assert "ANTHROPIC_BASE_URL" in check.hint


def test_the_probe_fails_when_a_personal_plugin_or_mcp_server_reaches_the_worker(stub, machine, worktree, task_dir,
                                                                                 tmp_path, factory_home):
    init = {"type": "system", "subtype": "init", "plugins": [{"name": "telegram", "source": "telegram@official"}],
            "mcp_servers": [{"name": "plugin:telegram:telegram", "status": "connected"}]}
    events = tmp_path / "probe-events.jsonl"
    events.write_text(json.dumps(init) + "\n")
    stub.set(result=str(events))
    check = C.probe_isolation(harness(str(stub.exe), GW_CONF.env), worktree, task_dir,
                              environ={**machine, **ENV_GW}, factory=factory_home)
    assert check.ok is False
    assert "telegram" in check.detail and "plugin:telegram" in check.detail


def test_the_probe_passes_when_only_builtin_plugins_are_loaded(stub, machine, worktree, task_dir, tmp_path, factory_home):
    init = {"type": "system", "subtype": "init",
            "plugins": [{"name": "cc-plugin-privacy", "source": "cc-plugin-privacy@builtin"}], "mcp_servers": []}
    events = tmp_path / "probe-events.jsonl"
    events.write_text(json.dumps(init) + "\n")
    stub.set(result=str(events))
    check = C.probe_isolation(harness(str(stub.exe), GW_CONF.env), worktree, task_dir,
                              environ={**machine, **ENV_GW}, factory=factory_home)
    assert check.ok is True


def test_stop_ends_the_worker_and_its_helper_sessions(stub, machine, make_ctx, tmp_path):
    stub.set(helpers=2, sleep=60)
    adapter = gateway_adapter(machine)
    handle = adapter.start(make_ctx(), GW_CONF, tmp_path / "worker.log")
    pids_file = stub.record / "helper-pids.txt"
    for _ in range(200):
        if pids_file.is_file():
            break
        time.sleep(0.05)
    helpers = [int(x) for x in pids_file.read_text().split()]
    assert helpers, "the stub did not start its helper sessions"
    adapter.stop(handle)
    adapter.wait(handle, 5)
    for pid in helpers:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


# ---- the same request gives the same evidence shape with helpers on and off -----------------------------------------

def test_helpers_on_and_off_give_attempt_evidence_of_the_same_shape(stub, machine, make_ctx, tmp_path):
    off, _ = attempt(gateway_adapter(machine), make_ctx(helpers=HelperPolicy("off", 0, [], None)), GW_CONF, tmp_path)
    on, _ = attempt(gateway_adapter(machine), make_ctx(helpers=HelperPolicy("auto", 2, ["api", "tests"], 10)), GW_CONF, tmp_path)
    assert {k: type(v) for k, v in vars(off).items()} == {k: type(v) for k, v in vars(on).items()}
