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

from process_gone import gone_within

from workers_helpers import harness, log_seen_while_running

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
    assert gone_within(pid), f"process {pid} is still running after the timeout"


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
def test_a_plugin_function_runs_on_the_engine_that_started_it(cmd_ctx, tmp_path, factory_home):
    """The runner is a child process. It must import the adapter's own `factory_engine`, not whichever copy the
    interpreter's site-packages happens to name (a stale editable install made three plugin tests fail)."""
    import factory_engine
    plugin = tmp_path / "plugin"
    (plugin / "checks").mkdir(parents=True)
    (plugin / "checks" / "__init__.py").write_text("")
    (plugin / "checks" / "where.py").write_text(
        "import factory_engine\n\ndef scan(ctx):\n    return {'status': 'passed', 'engine': factory_engine.__file__}\n")
    ctx = cmd_ctx(run=RunSpec(None, "checks.where:scan", []), plugin_dir=plugin)
    result, log = run(CommandAdapter(dict(os.environ)), ctx, tmp_path)
    assert result.exit == "ok"
    assert json.dumps(factory_engine.__file__) in log.read_text()


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


# ---- item 58: the TypeScript test step's own argv writes a JUnit file into the task folder under srt ----

def _typescript_test_argv() -> list[str]:
    import yaml
    kit = Path(__file__).resolve().parents[3] / "languages" / "typescript.yaml"
    return yaml.safe_load(kit.read_text())["variants"]["npm"]["test"]


def _stub_npm(bin_dir: Path, body: str) -> dict[str, str]:
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(f"#!/bin/sh\n{body}\n")
    npm.chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}


JUNIT_PASS = "<testsuite><testcase name=\"a\"/></testsuite>"
JUNIT_FAIL = "<testsuite><testcase name=\"a\"><failure/></testcase></testsuite>"


@needs_srt
def test_the_typescript_test_argv_writes_its_junit_file_into_the_task_folder_under_srt(
        cmd_ctx, tmp_path, factory_home, task_dir, worktree):
    """The profile's own `node -e` argv, run as a cmd task runs (CommandAdapter, under srt). A stub `npm` on PATH stands
    in for jest: it records its arguments and writes the file at $JEST_JUNIT_OUTPUT_FILE, which jest-junit would write.
    The real jest run of this argv was checked by hand (item 58 PR body). The report must land in the task's work
    folder, where the engine globs *.junit.xml, and the worktree must get no xml."""
    env = _stub_npm(tmp_path / "bin", f'echo "$@" > "$FACTORY_TASK_DIR/npm.args"; echo \'{JUNIT_PASS}\' > "$JEST_JUNIT_OUTPUT_FILE"')
    ctx = cmd_ctx(cmd=_typescript_test_argv())
    ctx.artifact_name = "test.junit.xml"
    result, log = run(CommandAdapter(env), ctx, tmp_path)
    assert result.exit == "ok", log.read_text()
    assert result.artifact == task_dir / "test.junit.xml" and result.artifact.is_file()
    assert (task_dir / "npm.args").read_text().strip() == "test -- --reporters=default --reporters=jest-junit"
    assert not list(worktree.glob("*.xml"))


@needs_srt
def test_a_failing_typescript_test_run_is_a_check_failure_and_keeps_its_report(
        cmd_ctx, tmp_path, factory_home, task_dir):
    env = _stub_npm(tmp_path / "bin", f"echo '{JUNIT_FAIL}' > \"$JEST_JUNIT_OUTPUT_FILE\"; exit 1")
    ctx = cmd_ctx(cmd=_typescript_test_argv())
    ctx.artifact_name = "test.junit.xml"
    result, _ = run(CommandAdapter(env), ctx, tmp_path)
    assert result.exit == "failed" and result.exit_code == 1
    assert (task_dir / "test.junit.xml").is_file()


def test_the_typescript_test_argv_refuses_to_run_without_a_task_folder(tmp_path):
    """Without FACTORY_TASK_DIR the step exits 2 and writes nothing, so the report cannot land in the worktree."""
    import subprocess
    env = _stub_npm(tmp_path / "bin", "exit 0")
    env.pop("FACTORY_TASK_DIR", None)
    r = subprocess.run(_typescript_test_argv(), env=env, capture_output=True, text=True)
    assert r.returncode == 2 and "FACTORY_TASK_DIR is not set" in r.stderr


# ---- item 58 follow-up: the Python test step writes a JUnit file through the same mechanism, with the real pytest ----

def _profile_test_argv(language: str, variant: str) -> list[str]:
    import yaml
    kit = Path(__file__).resolve().parents[3] / "languages" / f"{language}.yaml"
    return yaml.safe_load(kit.read_text())["variants"][variant]["test"]


needs_pytest = pytest.mark.skipif(shutil.which("pytest") is None, reason="pytest is not on PATH")


def _pytest_project(worktree: Path, body: str) -> None:
    (worktree / "pyproject.toml").write_text("[project]\nname = 'tmpproj'\n")
    (worktree / "test_sample.py").write_text(body)


@needs_srt
@needs_pytest
def test_the_python_test_argv_writes_a_junit_file_into_the_task_folder_under_srt(
        cmd_ctx, tmp_path, factory_home, task_dir, worktree):
    """The profile's own argv, run as a cmd task runs (CommandAdapter, under srt), with the real pytest on a temp project
    outside the repo. The report lands in the task's work folder, where the engine globs *.junit.xml, and the worktree
    gets no xml."""
    from factory_engine import gates
    _pytest_project(worktree, "def test_a():\n    assert 1 + 1 == 2\n\ndef test_b():\n    assert True\n")
    ctx = cmd_ctx(cmd=_profile_test_argv("python", "ruff"))
    result, log = run(CommandAdapter(dict(os.environ)), ctx, tmp_path)
    assert result.exit == "ok", log.read_text()
    report = task_dir / "test.junit.xml"
    assert report.is_file()
    assert gates.parse_junit([report]).total == 2
    assert not list(worktree.rglob("*.xml"))


@needs_srt
@needs_pytest
def test_a_failing_python_test_run_exits_one_and_still_leaves_its_report(
        cmd_ctx, tmp_path, factory_home, task_dir, worktree):
    from factory_engine import gates
    _pytest_project(worktree, "def test_a():\n    assert True\n\ndef test_b():\n    assert 1 == 2\n")
    ctx = cmd_ctx(cmd=_profile_test_argv("python", "ruff"))
    result, _ = run(CommandAdapter(dict(os.environ)), ctx, tmp_path)
    assert result.exit == "failed" and result.exit_code == 1
    parsed = gates.parse_junit([task_dir / "test.junit.xml"])
    assert parsed.total == 2 and parsed.failed == ["test_b"]


def test_the_python_test_argv_refuses_to_run_without_a_task_folder(tmp_path):
    """Without FACTORY_TASK_DIR the step exits 2 and runs no test, so the report cannot land in the worktree."""
    import subprocess
    env = {k: v for k, v in os.environ.items() if k != "FACTORY_TASK_DIR"}
    r = subprocess.run(_profile_test_argv("python", "ruff"), env=env, cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 2 and "FACTORY_TASK_DIR is not set" in r.stderr
    assert not list(tmp_path.rglob("*.xml"))


# ---- item 58 follow-up: the Maven test step copies surefire's reports into the task folder, with the real mvn ----

SUREFIRE_CACHED = (Path.home() / ".m2/repository/org/apache/maven/plugins/maven-surefire-plugin/3.2.5").is_dir()
needs_mvn = pytest.mark.skipif(shutil.which("mvn") is None or not SUREFIRE_CACHED,
                               reason="mvn and a cached surefire 3.2.5, compiler 3.13.0 and resources 3.3.1 are required (no network)")

POM = """<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>
<groupId>p</groupId><artifactId>probe</artifactId><version>1</version>
<properties><maven.compiler.source>17</maven.compiler.source><maven.compiler.target>17</maven.compiler.target>
<project.build.sourceEncoding>UTF-8</project.build.sourceEncoding></properties>
<dependencies><dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId><version>5.10.2</version><scope>test</scope></dependency></dependencies>
<build><plugins>
<plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-compiler-plugin</artifactId><version>3.13.0</version></plugin>
<plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-resources-plugin</artifactId><version>3.3.1</version></plugin>
<plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-surefire-plugin</artifactId><version>3.2.5</version></plugin>
</plugins></build></project>"""


def _maven_project(worktree: Path, assertion: str) -> None:
    (worktree / "pom.xml").write_text(POM)
    tests = worktree / "src" / "test" / "java" / "p"
    tests.mkdir(parents=True)
    (tests / "ProbeTest.java").write_text(
        "package p;\nimport org.junit.jupiter.api.Test;\nimport static org.junit.jupiter.api.Assertions.*;\n"
        f"class ProbeTest {{ @Test void a() {{ assertTrue(true); }} @Test void b() {{ {assertion} }} }}\n")


def _run_maven_step(worktree: Path, task_dir: Path):
    import subprocess
    env = {**os.environ, "FACTORY_TASK_DIR": str(task_dir)}
    return subprocess.run(_profile_test_argv("java", "maven"), cwd=worktree, env=env, capture_output=True, text=True)


@needs_mvn
def test_the_maven_test_argv_writes_one_merged_junit_file_into_the_task_folder(task_dir, worktree):
    """The profile's own argv with the real mvn, offline (MAVEN_ARGS=-o). Its reports are merged into test.junit.xml,
    the file the engine waits for (module 17A). This runs without srt: srt gives mvn no network, and the cached
    plugins are read from ~/.m2."""
    from factory_engine import gates
    _maven_project(worktree, "assertEquals(2, 1 + 1);")
    r = _run_maven_step(worktree, task_dir)
    assert r.returncode == 0, r.stdout + r.stderr
    assert gates.parse_junit([task_dir / "test.junit.xml"]).total == 2


@needs_mvn
def test_a_failing_maven_test_run_exits_nonzero_and_still_leaves_its_report(task_dir, worktree):
    from factory_engine import gates
    _maven_project(worktree, "assertEquals(1, 2);")
    r = _run_maven_step(worktree, task_dir)
    assert r.returncode != 0
    parsed = gates.parse_junit([task_dir / "test.junit.xml"])
    assert parsed.total == 2 and parsed.failed == ["b"]


@needs_mvn
def test_a_stale_surefire_report_from_an_earlier_run_is_not_copied(task_dir, worktree):
    """A build that fails before any test runs must not hand the gate the last run's report."""
    stale = worktree / "target" / "surefire-reports"
    stale.mkdir(parents=True)
    old = stale / "TEST-old.xml"
    old.write_text('<testsuite><testcase name="old"/></testsuite>')
    os.utime(old, (1_000_000_000, 1_000_000_000))
    (worktree / "pom.xml").write_text("<project>not a pom")
    r = _run_maven_step(worktree, task_dir)
    assert r.returncode != 0
    assert not list(task_dir.glob("*.junit.xml"))


def test_the_maven_test_argv_refuses_to_run_without_a_task_folder(tmp_path):
    import subprocess
    env = {k: v for k, v in os.environ.items() if k != "FACTORY_TASK_DIR"}
    r = subprocess.run(_profile_test_argv("java", "maven"), env=env, cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 2 and "FACTORY_TASK_DIR is not set" in r.stderr


# ---- item 58 follow-up: the Go test step converts `go test -json` to a JUnit file in the task folder, under srt ----

needs_go = pytest.mark.skipif(shutil.which("go") is None, reason="go is not on PATH")


def _go_project(worktree: Path, body: str) -> None:
    (worktree / "go.mod").write_text("module probe\n\ngo 1.21\n")
    pkg = worktree / "p"
    pkg.mkdir()
    (pkg / "p_test.go").write_text("package p\n\nimport \"testing\"\n\n" + body)


GO_PASS_AND_FAIL = ("func TestA(t *testing.T) {}\n\nfunc TestB(t *testing.T) { t.Fatal(\"boom\") }\n")
GO_PASS = "func TestA(t *testing.T) {}\n\nfunc TestC(t *testing.T) {}\n"


@needs_srt
@needs_go
def test_the_go_test_argv_converts_go_test_json_into_a_junit_file_in_the_task_folder_under_srt(
        cmd_ctx, tmp_path, factory_home, task_dir, worktree):
    from factory_engine import gates
    _go_project(worktree, GO_PASS)
    ctx = cmd_ctx(cmd=_profile_test_argv("go", "go"))
    result, log = run(CommandAdapter(dict(os.environ)), ctx, tmp_path, timeout=120)
    assert result.exit == "ok", log.read_text()
    report = task_dir / "test.junit.xml"
    assert report.is_file()
    parsed = gates.parse_junit([report])
    assert parsed.total == 2 and parsed.failed == []
    assert not list(worktree.rglob("*.xml"))


@needs_srt
@needs_go
def test_a_failing_go_test_run_exits_one_and_names_the_failed_test_in_its_report(
        cmd_ctx, tmp_path, factory_home, task_dir, worktree):
    from factory_engine import gates
    _go_project(worktree, GO_PASS_AND_FAIL)
    ctx = cmd_ctx(cmd=_profile_test_argv("go", "go"))
    result, _ = run(CommandAdapter(dict(os.environ)), ctx, tmp_path, timeout=120)
    assert result.exit == "failed" and result.exit_code == 1
    parsed = gates.parse_junit([task_dir / "test.junit.xml"])
    assert parsed.total == 2 and parsed.failed == ["TestB"]


@needs_go
def test_a_package_that_does_not_build_is_a_failed_case_not_an_empty_report(tmp_path, task_dir, worktree):
    import subprocess
    from factory_engine import gates
    (worktree / "go.mod").write_text("module probe\n\ngo 1.21\n")
    (worktree / "p").mkdir()
    (worktree / "p" / "p_test.go").write_text("package p\n\nfunc broken( {\n")
    env = {**os.environ, "FACTORY_TASK_DIR": str(task_dir)}
    r = subprocess.run(_profile_test_argv("go", "go"), cwd=worktree, env=env, capture_output=True, text=True)
    assert r.returncode != 0
    parsed = gates.parse_junit([task_dir / "test.junit.xml"])
    assert parsed.total == 1 and parsed.failed == ["probe/p"]


def test_the_go_test_argv_refuses_to_run_without_a_task_folder(tmp_path):
    import subprocess
    env = {k: v for k, v in os.environ.items() if k != "FACTORY_TASK_DIR"}
    r = subprocess.run(_profile_test_argv("go", "go"), env=env, cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 2 and "FACTORY_TASK_DIR is not set" in r.stderr


# ---- item 58 follow-up: the Gradle test step copies Gradle's JUnit XML into the task folder, with the real gradlew ----

GRADLE_DIST_CACHED = (Path.home() / ".gradle/wrapper/dists/gradle-9.9.2-bin").is_dir()
needs_gradle = pytest.mark.skipif(shutil.which("gradle") is None or shutil.which("java") is None or not GRADLE_DIST_CACHED,
                                  reason="gradle 9.9.2 (to write the wrapper), java and the cached 9.9.2 distribution "
                                         "and JUnit 5.10.2 are required (no network)")


def _gradle_project(worktree: Path, assertion: str) -> None:
    """A JUnit 5 project with its own wrapper, as the profile expects (`gradlew` is the repo's, module 17A)."""
    import subprocess
    (worktree / "settings.gradle").write_text('rootProject.name = "probe"\n')
    (worktree / "build.gradle").write_text(
        'plugins { id "java" }\nrepositories { mavenCentral() }\ndependencies {\n'
        '    testImplementation "org.junit.jupiter:junit-jupiter:5.10.2"\n'
        '    testRuntimeOnly "org.junit.platform:junit-platform-launcher:1.10.2"\n}\ntest { useJUnitPlatform() }\n')
    tests = worktree / "src" / "test" / "java" / "probe"
    tests.mkdir(parents=True)
    (tests / "ProbeTest.java").write_text(
        "package probe;\nimport org.junit.jupiter.api.Test;\nimport static org.junit.jupiter.api.Assertions.*;\n"
        f"class ProbeTest {{ @Test void a() {{ assertTrue(true); }} @Test void b() {{ {assertion} }} }}\n")
    subprocess.run(["gradle", "wrapper", "--gradle-version", "9.9.2", "--offline"], cwd=worktree, check=True,
                   capture_output=True)


def _run_gradle_step(worktree: Path, task_dir: Path):
    import subprocess
    # Offline, from ~/.gradle (the cached distribution and JUnit), as the Maven tests read ~/.m2. The step's own default
    # home is the task folder, which the srt test in test_step_network.py uses.
    env = {**os.environ, "FACTORY_TASK_DIR": str(task_dir), "GRADLE_USER_HOME": str(Path.home() / ".gradle"),
           "GRADLE_OPTS": "-Dorg.gradle.offline=true"}
    return subprocess.run(_profile_test_argv("java", "gradle"), cwd=worktree, env=env, capture_output=True, text=True)


@needs_gradle
def test_the_gradle_test_argv_writes_one_junit_file_into_the_task_folder(task_dir, worktree):
    """The profile's own argv with the real gradlew, offline. Gradle writes build/test-results/test/TEST-*.xml; the step
    copies them into test.junit.xml, the file the engine waits for (module 17A)."""
    from factory_engine import gates
    _gradle_project(worktree, "assertEquals(2, 1 + 1);")
    r = _run_gradle_step(worktree, task_dir)
    assert r.returncode == 0, r.stdout + r.stderr
    assert gates.parse_junit([task_dir / "test.junit.xml"]).total == 2


@needs_gradle
def test_a_failing_gradle_test_run_exits_nonzero_and_still_leaves_its_report(task_dir, worktree):
    from factory_engine import gates
    _gradle_project(worktree, "assertEquals(1, 2);")
    r = _run_gradle_step(worktree, task_dir)
    assert r.returncode != 0
    parsed = gates.parse_junit([task_dir / "test.junit.xml"])
    assert parsed.total == 2 and parsed.failed == ["b()"]


@needs_gradle
def test_a_second_gradle_run_with_nothing_changed_still_runs_the_tests_and_writes_a_report(task_dir, worktree, tmp_path):
    """Gradle skips an up-to-date `test` task and writes no new XML; the step forces the run, so a retry is not empty."""
    from factory_engine import gates
    _gradle_project(worktree, "assertEquals(2, 1 + 1);")
    assert _run_gradle_step(worktree, task_dir).returncode == 0
    (task_dir / "test.junit.xml").unlink()
    r = _run_gradle_step(worktree, task_dir)
    assert r.returncode == 0, r.stdout + r.stderr
    assert gates.parse_junit([task_dir / "test.junit.xml"]).total == 2


@needs_gradle
def test_a_stale_gradle_report_from_an_earlier_run_is_not_copied(task_dir, worktree):
    """A build that fails before any test runs must not hand the gate the last run's report."""
    _gradle_project(worktree, "assertEquals(2, 1 + 1);")
    stale = worktree / "build" / "test-results" / "test"
    stale.mkdir(parents=True)
    old = stale / "TEST-old.xml"
    old.write_text('<testsuite><testcase name="old"/></testsuite>')
    os.utime(old, (1_000_000_000, 1_000_000_000))
    (worktree / "build.gradle").write_text("this is not groovy {{{")
    r = _run_gradle_step(worktree, task_dir)
    assert r.returncode != 0
    assert not list(task_dir.glob("*.junit.xml"))


def test_the_gradle_test_argv_refuses_to_run_without_a_task_folder(tmp_path):
    import subprocess
    env = {k: v for k, v in os.environ.items() if k != "FACTORY_TASK_DIR"}
    r = subprocess.run(_profile_test_argv("java", "gradle"), env=env, cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 2 and "FACTORY_TASK_DIR is not set" in r.stderr


# ---- item 58 follow-up: the C# test step runs `dotnet test --logger trx` and converts it to JUnit, with the real dotnet ----

NUGET_CACHED = all((Path.home() / ".nuget/packages" / p).is_dir() for p in
                   ("xunit/2.9.3", "xunit.runner.visualstudio/3.1.5", "microsoft.net.test.sdk/17.14.1", "coverlet.collector"))
needs_dotnet = pytest.mark.skipif(shutil.which("dotnet") is None or not NUGET_CACHED,
                                  reason="dotnet and the cached xunit 2.9.3, runner 3.1.5, Test.Sdk 17.14.1 and coverlet are required (no network)")

CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
<PropertyGroup><TargetFramework>net%s</TargetFramework><ImplicitUsings>enable</ImplicitUsings><IsPackable>false</IsPackable></PropertyGroup>
<ItemGroup>
<PackageReference Include="coverlet.collector" Version="6.0.4" />
<PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.14.1" />
<PackageReference Include="xunit" Version="2.9.3" />
<PackageReference Include="xunit.runner.visualstudio" Version="3.1.5" />
</ItemGroup>
<ItemGroup><Using Include="Xunit" /></ItemGroup>
</Project>"""


def _dotnet_project(worktree: Path, body: str) -> None:
    import re
    import subprocess
    major = re.match(r"(\d+)\.", subprocess.run(["dotnet", "--version"], capture_output=True, text=True).stdout)[1]
    (worktree / "Probe.csproj").write_text(CSPROJ % (major + ".0"))
    (worktree / "ProbeTests.cs").write_text("namespace Probe;\npublic class ProbeTests {\n" + body + "\n}\n")


DOTNET_PASS = "[Fact] public void A() { Assert.True(true); }\n[Fact] public void B() { Assert.Equal(2, 1 + 1); }"
DOTNET_FAIL = ("[Fact] public void A() { Assert.True(true); }\n[Fact] public void B() { Assert.Equal(1, 2); }\n"
               "[Fact(Skip = \"later\")] public void C() { }")


def _run_dotnet_step(worktree: Path, task_dir: Path):
    import subprocess
    env = {**os.environ, "FACTORY_TASK_DIR": str(task_dir), "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
           "DOTNET_NOLOGO": "1"}
    return subprocess.run(_profile_test_argv("csharp", "dotnet"), cwd=worktree, env=env, capture_output=True, text=True)


@needs_dotnet
def test_the_dotnet_test_argv_writes_a_junit_file_into_the_task_folder(task_dir, worktree):
    """The profile's own argv with the real dotnet, offline from the NuGet cache. The SDK bundles no `junit` logger (the
    run says `Could not find a test logger ... 'junit'`), so the step uses the bundled `trx` logger and converts it."""
    from factory_engine import gates
    _dotnet_project(worktree, DOTNET_PASS)
    r = _run_dotnet_step(worktree, task_dir)
    assert r.returncode == 0, r.stdout + r.stderr
    assert gates.parse_junit([task_dir / "test.junit.xml"]).total == 2
    assert not list(worktree.rglob("*.trx")), "the trx file belongs in the task folder, not the repo"


@needs_dotnet
def test_a_failing_dotnet_test_run_exits_nonzero_names_the_failed_test_and_marks_a_skip(task_dir, worktree):
    import xml.etree.ElementTree as ET
    from factory_engine import gates
    _dotnet_project(worktree, DOTNET_FAIL)
    r = _run_dotnet_step(worktree, task_dir)
    assert r.returncode != 0
    parsed = gates.parse_junit([task_dir / "test.junit.xml"])
    assert parsed.total == 3 and parsed.failed == ["B"]
    skipped = [c.get("name") for c in ET.parse(task_dir / "test.junit.xml").getroot().iter("testcase")
               if c.find("skipped") is not None]
    assert skipped == ["C"]


@needs_dotnet
def test_a_dotnet_build_error_leaves_no_report_so_the_task_is_not_done(task_dir, worktree):
    """A project that does not build runs no test and writes no trx, so no JUnit file (the engine's gate then blocks)."""
    _dotnet_project(worktree, "this is not C#")
    r = _run_dotnet_step(worktree, task_dir)
    assert r.returncode != 0
    assert not list(task_dir.glob("*.junit.xml"))


def test_the_dotnet_test_argv_refuses_to_run_without_a_task_folder(tmp_path):
    import subprocess
    env = {k: v for k, v in os.environ.items() if k != "FACTORY_TASK_DIR"}
    r = subprocess.run(_profile_test_argv("csharp", "dotnet"), env=env, cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 2 and "FACTORY_TASK_DIR is not set" in r.stderr
