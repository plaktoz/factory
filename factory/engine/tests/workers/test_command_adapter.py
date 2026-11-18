"""Module 9 acceptance criteria for CommandAdapter: deterministic tasks run under srt, with the worker's rules.

These need the real `srt` (0.0.83) and Node 22.12 or later. They skip when srt is not installed, and `factory doctor`
fails in that case, so a missing srt is never a silent pass in a real run.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from factory_engine.adapters.worker import sandbox
from factory_engine.adapters.worker.command import CommandAdapter, classify_exit
from factory_engine.errors import FactoryError
from factory_engine.types import RunSpec

from conftest import harness, log_seen_while_running

SRT = shutil.which("srt")
needs_srt = pytest.mark.skipif(SRT is None or sandbox.node_version() is None or sandbox.node_version()[:2] < (22, 12),
                               reason="srt 0.0.83 and Node 22.12+ are required (module 9)")


@pytest.fixture
def cmd_ctx(make_ctx, tmp_path):
    def make(**kw):
        ctx = make_ctx(**{k: v for k, v in kw.items() if k in ("task_id", "attempt", "bash")})
        ctx.skill = None
        ctx.cmd = kw.get("cmd")
        ctx.run = kw.get("run")
        ctx.plugin_dir = kw.get("plugin_dir")
        return ctx
    return make


@pytest.fixture
def factory_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(home))
    return home


def run(adapter, ctx, tmp_path, timeout=60):
    log = tmp_path / "worker.log"
    handle = adapter.start(ctx, harness("command"), log)
    return adapter.wait(handle, timeout), log


# ---- exit codes -----------------------------------------------------------------------------------------------------

def test_for_a_cmd_zero_passes_and_any_other_exit_fails_the_check():
    assert classify_exit("cmd", 0) == "passed"
    assert classify_exit("cmd", 1) == "check_failed"
    assert classify_exit("cmd", 3) == "check_failed"
    assert classify_exit("cmd", 127) == "check_failed"


def test_for_a_script_or_function_zero_one_and_two_or_more_map_to_passed_check_failed_and_task_error():
    assert classify_exit("script", 0) == "passed"
    assert classify_exit("script", 1) == "check_failed"
    assert classify_exit("script", 2) == "task_error"
    assert classify_exit("python", 3) == "task_error"


def test_a_missing_result_is_a_task_error():
    assert classify_exit("cmd", None) == "task_error"


# ---- arguments stay arguments ----------------------------------------------------------------------------------------

def test_an_argument_with_shell_syntax_reaches_the_program_as_one_argument():
    argv = ["printf", "%s|", "c;touch X", "$(touch Y)", "a b"]
    wrapped = sandbox.srt_command("/bin/srt", Path("/s.json"), argv)
    assert wrapped[:4] == ["/bin/srt", "-s", "/s.json", "-c"]
    shell = wrapped[4]
    assert "'c;touch X'" in shell and "'$(touch Y)'" in shell and "'a b'" in shell


@needs_srt
def test_shell_syntax_in_an_argument_creates_no_file(make_ctx, worktree, task_dir, tmp_path, factory_home, cmd_ctx):
    marker_x = worktree / "X"
    marker_y = worktree / "Y"
    ctx = cmd_ctx(cmd=["printf", "%s\n", f"c;touch {marker_x}", f"$(touch {marker_y})"])
    result, _ = run(CommandAdapter(dict(os.environ)), ctx, tmp_path)
    assert result.exit == "ok"
    assert not marker_x.exists() and not marker_y.exists()


# ---- exit codes through srt ----------------------------------------------------------------------------------------

@needs_srt
@pytest.mark.parametrize("code", [0, 3])
def test_an_exit_code_arrives_unchanged_through_srt(cmd_ctx, tmp_path, factory_home, code):
    ctx = cmd_ctx(cmd=["sh", "-c", f"exit {code}"])
    result, _ = run(CommandAdapter(dict(os.environ)), ctx, tmp_path)
    assert result.exit_code == code
    assert result.exit == ("ok" if code == 0 else "failed")


@needs_srt
def test_a_missing_binary_is_reported_as_binary_missing_not_a_check_failure(cmd_ctx, tmp_path, factory_home):
    ctx = cmd_ctx(cmd=["definitely-not-a-real-binary-xyz"])
    result, _ = run(CommandAdapter(dict(os.environ)), ctx, tmp_path)
    assert result.exit_code == 127
    assert result.exit == "failed"


# ---- timeout and stop -------------------------------------------------------------------------------------------

@needs_srt
def test_a_command_is_killed_at_its_timeout(cmd_ctx, tmp_path, factory_home, task_dir):
    pid_file = task_dir / "child.pid"
    ctx = cmd_ctx(cmd=["sh", "-c", f"echo $$ > {pid_file}; sleep 30"])
    result, _ = run(CommandAdapter(dict(os.environ)), ctx, tmp_path, timeout=3)
    assert result.exit == "timeout"
    assert_pid_gone(pid_file)


@needs_srt
def test_a_plugin_script_is_killed_at_its_timeout(cmd_ctx, tmp_path, factory_home, task_dir):
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    pid_file = task_dir / "child.pid"
    (plugin / "scripts" / "slow.py").write_text(
        f"import os, time\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))\ntime.sleep(30)\n")
    ctx = cmd_ctx(run=RunSpec("scripts/slow.py", None, []), plugin_dir=plugin)
    result, _ = run(CommandAdapter(dict(os.environ)), ctx, tmp_path, timeout=3)
    assert result.exit == "timeout"
    assert_pid_gone(pid_file)


@needs_srt
def test_a_plugin_function_is_killed_at_its_timeout(cmd_ctx, tmp_path, factory_home, task_dir):
    plugin = tmp_path / "plugin"
    (plugin / "checks").mkdir(parents=True)
    (plugin / "checks" / "__init__.py").write_text("")
    pid_file = task_dir / "child.pid"
    (plugin / "checks" / "slow.py").write_text(
        f"import os, time\n\ndef scan(ctx):\n    open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n    time.sleep(30)\n")
    ctx = cmd_ctx(run=RunSpec(None, "checks.slow:scan", []), plugin_dir=plugin)
    result, _ = run(CommandAdapter(dict(os.environ)), ctx, tmp_path, timeout=3)
    assert result.exit == "timeout"
    assert_pid_gone(pid_file)


def assert_pid_gone(pid_file):
    """The child wrote its PID before it slept. After the timeout no process with that PID may still run."""
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@needs_srt
def test_a_stop_ends_the_command(cmd_ctx, tmp_path, factory_home):
    ad = CommandAdapter(dict(os.environ))
    handle = ad.start(cmd_ctx(cmd=["sleep", "30"]), harness("command"), tmp_path / "worker.log")
    ad.stop(handle)
    result = ad.wait(handle, 5)
    assert result.exit == "killed"


# ---- scripts and plugin functions ------------------------------------------------------------------------------

@needs_srt
def test_a_plugin_python_function_gets_the_task_context_on_stdin_and_its_result_on_stdout(cmd_ctx, tmp_path, factory_home):
    # module 5: the function gets FACTORY_RUN_ID, FACTORY_STAGE, FACTORY_TASK_ID, FACTORY_WORKTREE and FACTORY_TASK_DIR
    plugin = tmp_path / "plugin"
    (plugin / "checks").mkdir(parents=True)
    (plugin / "checks" / "__init__.py").write_text("")
    (plugin / "checks" / "licenses.py").write_text(
        "def scan(ctx):\n    return {'status': 'passed', 'found': ctx['FACTORY_TASK_ID']}\n")
    ctx = cmd_ctx(run=RunSpec(None, "checks.licenses:scan", []), plugin_dir=plugin)
    result, log = run(CommandAdapter(dict(os.environ)), ctx, tmp_path)
    assert result.exit == "ok" and result.exit_code == 0
    assert '"found": "backend"' in log.read_text()


@needs_srt
def test_a_plugin_function_that_raises_is_a_task_error(cmd_ctx, tmp_path, factory_home):
    plugin = tmp_path / "plugin"
    (plugin / "checks").mkdir(parents=True)
    (plugin / "checks" / "__init__.py").write_text("")
    (plugin / "checks" / "bad.py").write_text("def scan(ctx):\n    raise RuntimeError('boom')\n")
    ctx = cmd_ctx(run=RunSpec(None, "checks.bad:scan", []), plugin_dir=plugin)
    result, _ = run(CommandAdapter(dict(os.environ)), ctx, tmp_path)
    assert result.exit_code == 2


@needs_srt
def test_a_plugin_script_exit_1_is_a_check_failure_and_exit_2_a_task_error(cmd_ctx, tmp_path, factory_home):
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    (plugin / "scripts" / "check.py").write_text("import sys\nsys.exit(int(sys.argv[1]))\n")
    for code, want in ((1, "check_failed"), (2, "task_error")):
        ctx = cmd_ctx(run=RunSpec("scripts/check.py", None, [str(code)]), plugin_dir=plugin)
        ad = CommandAdapter(dict(os.environ))
        result, _ = run(ad, ctx, tmp_path)
        assert classify_exit("script", result.exit_code) == want


# ---- the sandbox, commands and the write boundary --------------------------------------------------------------

@needs_srt
def test_a_command_cannot_read_the_factory_home(cmd_ctx, tmp_path, factory_home, worktree):
    secret = factory_home / "config.yaml"
    secret.write_text("secret: value\n")
    ctx = cmd_ctx(cmd=["cat", str(secret)])
    result, _ = run(CommandAdapter(dict(os.environ)), ctx, tmp_path)
    assert result.exit == "failed" and result.exit_code != 0


@needs_srt
def test_a_command_cannot_read_the_codex_key_file(cmd_ctx, tmp_path, factory_home, monkeypatch):
    home = tmp_path / "userhome"
    (home / ".codex").mkdir(parents=True)
    key = home / ".codex" / "auth.json"
    key.write_text('{"OPENAI_API_KEY": "sk-SECRET"}')
    monkeypatch.setenv("HOME", str(home))
    result, log = run(CommandAdapter(dict(os.environ)), cmd_ctx(cmd=["cat", str(key)]), tmp_path)
    assert result.exit == "failed" and result.exit_code != 0
    assert "sk-SECRET" not in log.read_text()


@needs_srt
def test_a_command_can_write_inside_the_worktree_and_task_folder_but_not_outside_both(cmd_ctx, tmp_path, factory_home,
                                                                                       worktree, task_dir):
    inside = worktree / "ok.txt"
    task_file = task_dir / "ok.txt"
    outside = tmp_path / "outside.txt"
    ad = CommandAdapter(dict(os.environ))
    r1, _ = run(ad, cmd_ctx(cmd=["sh", "-c", f"echo a > {inside}"]), tmp_path)
    r2, _ = run(ad, cmd_ctx(cmd=["sh", "-c", f"echo b > {task_file}"]), tmp_path)
    r3, _ = run(ad, cmd_ctx(cmd=["sh", "-c", f"echo c > {outside}"]), tmp_path)
    assert (r1.exit, r2.exit) == ("ok", "ok")
    assert r3.exit == "failed"
    assert inside.exists() and task_file.exists() and not outside.exists()


@needs_srt
def test_a_worker_cannot_write_engine_state_in_the_run_folder_outside_its_work_folder(cmd_ctx, tmp_path, factory_home,
                                                                                    task_dir):
    # The run folder holds task.json, notes.jsonl and the other engine state. Only work/ is writable (module 9).
    run_dir = task_dir.parent.parent.parent
    task_json = task_dir.parent / "task.json"
    notes = run_dir / "notes.jsonl"
    ad = CommandAdapter(dict(os.environ))
    r1, _ = run(ad, cmd_ctx(cmd=["sh", "-c", f"echo x > {task_json}"]), tmp_path)
    r2, _ = run(ad, cmd_ctx(cmd=["sh", "-c", f"echo x > {notes}"]), tmp_path)
    assert (r1.exit, r2.exit) == ("failed", "failed")
    assert not task_json.exists() and not notes.exists()


@needs_srt
def test_a_npm_style_cache_lands_under_the_task_folder_and_a_write_to_home_npm_still_fails(cmd_ctx, tmp_path, factory_home,
                                                                                            task_dir):
    cache = task_dir / "cache" / "npm"
    ctx = cmd_ctx(cmd=["sh", "-c", f"mkdir -p \"$npm_config_cache\" && echo ok > \"$npm_config_cache/marker\""])
    result, _ = run(CommandAdapter(dict(os.environ)), ctx, tmp_path)
    assert result.exit == "ok"
    assert (cache / "marker").exists()
    home_npm = Path(os.path.expanduser("~")) / ".npm-factory-probe-do-not-create"
    blocked, _ = run(CommandAdapter(dict(os.environ)), cmd_ctx(cmd=["sh", "-c", f"echo x > {home_npm}"]), tmp_path)
    assert blocked.exit == "failed"
    assert not home_npm.exists()


@needs_srt
@pytest.mark.skipif(shutil.which("npm") is None, reason="npm is not installed")
def test_real_npm_reports_its_cache_under_the_task_folder(cmd_ctx, tmp_path, factory_home, task_dir):
    ctx = cmd_ctx(cmd=["npm", "config", "get", "cache"])
    result, log = run(CommandAdapter(dict(os.environ)), ctx, tmp_path)
    assert result.exit == "ok"
    assert log.read_text().strip() == str(task_dir / "cache" / "npm")


def test_a_command_with_no_srt_is_refused_before_it_runs(cmd_ctx, tmp_path, factory_home, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))  # srt is looked up on the process PATH, so an empty PATH hides it
    with pytest.raises(FactoryError) as e:
        CommandAdapter({"PATH": str(empty)}).start(cmd_ctx(cmd=["true"]), harness("command"), tmp_path / "l.log")
    assert e.value.code == "sandbox.srt_missing"
    assert not (tmp_path / "marker").exists()


# ---- the srt settings and checks -----------------------------------------------------------------------------------

def test_the_srt_settings_have_the_worker_read_and_write_rules(tmp_path, worktree, task_dir, factory_home):
    doc = sandbox.srt_settings(worktree, task_dir, factory_home)
    fs = doc["filesystem"]
    assert str(factory_home.resolve()) in fs["denyRead"]
    assert str(task_dir.resolve()) in fs["allowRead"]
    assert set(fs["allowWrite"]) == {str(worktree.resolve()), str(task_dir.resolve())}
    assert "denyWrite" in fs and "deniedDomains" in doc["network"] and doc["network"]["allowedDomains"] == []


@needs_srt
def test_the_srt_canary_passes_on_the_real_sandbox(worktree, task_dir, factory_home):
    result = sandbox.canary_srt(worktree, task_dir, factory_home)
    assert result.ok, result.detail


@needs_srt
def test_the_srt_canary_names_an_open_route_when_the_settings_leave_one(worktree, task_dir, factory_home, monkeypatch):
    """Detection: with the factory home left out of denyRead, the read routes are open, and the canary must say so."""
    real = sandbox.srt_settings

    def leaky(wt, td, factory=None):
        doc = real(wt, td, factory)
        doc["filesystem"]["denyRead"] = []
        return doc

    monkeypatch.setattr(sandbox, "srt_settings", leaky)
    result = sandbox.canary_srt(worktree, task_dir, factory_home)
    assert result.ok is False
    assert "sandbox.canary_open" in result.detail and "read via cat" in result.detail


def test_doctor_fails_when_srt_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(sandbox, "srt_bin", lambda: None)
    check = sandbox.check_srt()
    assert check.ok is False and "sandbox.srt_missing" in check.detail


def test_doctor_fails_when_node_is_older_than_22_12(monkeypatch):
    monkeypatch.setattr(sandbox, "srt_bin", lambda: "/usr/local/bin/srt")
    monkeypatch.setattr(sandbox, "node_version", lambda: (20, 11, 0))
    check = sandbox.check_srt()
    assert check.ok is False and "sandbox.node_old" in check.detail


# ---- the environment of a command ---------------------------------------------------------------------------------

def test_a_command_gets_the_minimal_base_the_run_ids_and_the_cache_folders(cmd_ctx, tmp_path, task_dir, factory_home):
    ad = CommandAdapter({"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "AWS_SECRET_ACCESS_KEY": "aws-SECRET"})
    ctx = cmd_ctx(cmd=["true"])
    env = ad._env(ctx)
    assert env["FACTORY_TASK_DIR"] == str(task_dir)
    assert env["FACTORY_RUN_ID"] == "run-1" and env["FACTORY_TASK_ID"] == "backend"
    assert env["npm_config_cache"].startswith(str(task_dir))
    assert "AWS_SECRET_ACCESS_KEY" not in env


@needs_srt
def test_worker_log_has_a_cmd_tasks_output_while_it_is_still_running(cmd_ctx, tmp_path, factory_home):
    ctx = cmd_ctx(cmd=["sh", "-c", "echo step one; sleep 60"])
    adapter, log = CommandAdapter(dict(os.environ)), tmp_path / "worker.log"
    handle = adapter.start(ctx, harness("command"), log)
    seen, running = log_seen_while_running(adapter, handle, log, "step one")
    assert seen and running
