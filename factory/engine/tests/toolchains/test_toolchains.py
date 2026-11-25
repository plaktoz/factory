"""Module 17A acceptance criteria. Fixture repos for each shipped language. Where the real tool is not installed
on this machine (gradle, golangci-lint, dotnet, prettier, eslint), a stub on PATH stands in and the test says so."""

import os
import stat
from pathlib import Path

import pytest

from factory_engine import toolchains
from factory_engine.config import Config
from factory_engine.errors import FactoryError
from factory_engine.types import GateContext, GateSpec, Run, Request, Source

CFG = Config(machine={}, repo={})


def fixture(tmp_path, files):
    w = tmp_path / "wt"
    for rel, text in files.items():
        (w / rel).parent.mkdir(parents=True, exist_ok=True)
        (w / rel).write_text(text)
    return w


def stub(bin_dir: Path, name: str, body: str = "exit 0") -> None:
    bin_dir.mkdir(exist_ok=True)
    p = bin_dir / name
    p.write_text(f"#!/bin/sh\n{body}\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def path_with(monkeypatch, tmp_path):
    """Put stub tools first on PATH for one test; the stub directory is returned."""
    bins = tmp_path / "bin"
    monkeypatch.setenv("PATH", f"{bins}{os.pathsep}{os.environ['PATH']}")
    return bins


# ---- detection: the right variant for each shipped language ----

@pytest.mark.parametrize("files,name,variant", [
    ({"pom.xml": "<project/>"}, "java", "maven"),
    ({"build.gradle": "apply plugin: 'java'"}, "java", "gradle"),
    ({"build.gradle.kts": "plugins {}"}, "java", "gradle"),
    ({"package.json": "{}"}, "typescript", "npm"),
    ({"pyproject.toml": "[project]\n"}, "python", "ruff"),
    ({"go.mod": "module x\n"}, "go", "go"),
    ({"App.csproj": "<Project/>"}, "csharp", "dotnet"),
])
def test_detection_picks_the_right_profile_and_variant(tmp_path, files, name, variant):
    w = fixture(tmp_path, files)
    found = toolchains.detect(w, CFG)
    assert [(t.name, t.variant) for t in found] == [(name, variant)]


def test_a_repo_with_java_and_typescript_detects_both(tmp_path):
    w = fixture(tmp_path, {"pom.xml": "<project/>", "package.json": "{}"})
    assert sorted(t.name for t in toolchains.detect(w, CFG)) == ["java", "typescript"]


def test_a_repo_with_no_known_marker_detects_nothing(tmp_path):
    assert toolchains.detect(fixture(tmp_path, {"README.md": "x"}), CFG) == []


def test_the_java_profile_names_the_spec_commands(tmp_path):
    w = fixture(tmp_path, {"pom.xml": "<project/>"})
    tc = toolchains.detect(w, CFG)[0]
    assert tc.commands["format"] == ["mvn", "-q", "spotless:apply"]
    assert tc.commands["build"] == ["mvn", "-q", "-DskipTests", "package"]


def test_a_repo_profile_replaces_the_shipped_one(tmp_path):
    w = fixture(tmp_path, {"pom.xml": "<project/>"})
    override = w / ".factory" / "config" / "languages"
    override.mkdir(parents=True)
    (override / "java.yaml").write_text("name: java\ndetect: {any_file: [pom.xml]}\nfiles: ['**/*.java']\n"
                                        "variants:\n  maven:\n    when: {file: pom.xml}\n    test: [mvn, -q, verify]\n")
    tc = toolchains.detect(w, CFG)[0]
    assert tc.commands == {"test": ["mvn", "-q", "verify"]}


# ---- steps: formatter on a real tool, missing tools, exit codes ----

def test_a_missing_tool_fails_fast_with_its_name(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    w = fixture(tmp_path, {"pom.xml": "<project/>"})
    tc = toolchains.detect(w, CFG)[0]
    with pytest.raises(FactoryError) as e:
        toolchains.run_step(tc, "format", w, log=tmp_path / "log")
    assert e.value.code == "config.invalid" and "mvn" in e.value.message


def test_a_formatter_that_exits_non_zero_is_reported_not_raised(tmp_path, path_with):
    stub(path_with, "mvn", "echo 'spotless failed'; exit 3")
    w = fixture(tmp_path, {"pom.xml": "<project/>"})
    res = toolchains.run_step(toolchains.detect(w, CFG)[0], "format", w, log=tmp_path / "log")
    assert res.exit_code == 3 and not res.ok and "spotless failed" in res.output_tail


def test_a_step_with_no_command_succeeds_without_running_anything(tmp_path):
    w = fixture(tmp_path, {"pyproject.toml": "[project]\n"})
    tc = toolchains.detect(w, CFG)[0]
    res = toolchains.run_step(tc, "build", w, log=tmp_path / "log")  # python build is empty (Unspecified in the spec)
    assert res.ok and res.exit_code == 0


def test_run_step_writes_its_log_and_refuses_an_unknown_step(tmp_path, path_with):
    stub(path_with, "mvn", "echo hello-from-mvn")
    w = fixture(tmp_path, {"pom.xml": "<project/>"})
    log = tmp_path / "out" / "mvn.log"
    toolchains.run_step(toolchains.detect(w, CFG)[0], "build", w, log=log)  # build is a bare mvn; test now needs a task folder
    assert "hello-from-mvn" in log.read_text()
    with pytest.raises(FactoryError, match="unknown step"):
        toolchains.run_step(toolchains.detect(w, CFG)[0], "deploy", w, log=log)


def test_the_real_python_formatter_runs_on_a_fixture(tmp_path, monkeypatch):
    """The real ruff formats unformatted code in place. ruff is not on the shell PATH here; `uv run --with ruff`
    provides it, so the test puts that ruff on PATH and runs the real tool."""
    import shutil
    import subprocess
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv not installed, so no ruff")
    ruff_dir = subprocess.run([uv, "tool", "dir", "--bin"], capture_output=True, text=True).stdout.strip()
    probe = subprocess.run([uv, "run", "--no-project", "--with", "ruff", "python", "-c",
                            "import shutil,sys;print(shutil.which('ruff') or '')"], capture_output=True, text=True)
    ruff_path = probe.stdout.strip()
    if not ruff_path:
        pytest.skip("ruff could not be provided by uv")
    monkeypatch.setenv("PATH", f"{Path(ruff_path).parent}{os.pathsep}{os.environ['PATH']}")
    w = fixture(tmp_path, {"pyproject.toml": "[project]\n", "app.py": "x=1\n"})
    tc = toolchains.detect(w, CFG)[0]
    res = toolchains.run_step(tc, "format", w, log=tmp_path / "log")
    assert res.ok, res.output_tail
    assert (w / "app.py").read_text() == "x = 1\n"


# ---- the lint gate and its feedback ----

def ctx(w):
    src = Source("cli", "r", "t", "b", [], None, [])
    req = Request("r", src, "sha", "repo", "t", "bug", "explicit", None, [])
    return GateContext(run=Run("r1", "repo", "k", w, req, None, None, w, "running", None, [], {}, None, None, None, "", "x", None),
                       stage="fix", task_id=None, worktree=w, task_dir=None, artifact=None, task_base=None,
                       scope=[], deny=[], cfg=CFG)


def test_a_lint_violation_fails_lint_clean_and_lists_file_line_and_rule(tmp_path, path_with):
    stub(path_with, "ruff", "echo 'app.py:4:1: F401 `os` imported but unused'; exit 1")
    w = fixture(tmp_path, {"pyproject.toml": "[project]\n", "app.py": "import os\n"})
    spec = GateSpec(kind="check", cmd=None, check="lint-clean", schema=None, args={})
    res = toolchains.check_lint_clean(spec, ctx(w))
    assert not res.passed and res.gate == "lint-clean"
    f = res.details["findings"][0]
    assert (f["file"], f["line"], f["rule"]) == ("app.py", 4, "F401")


def test_a_lint_violation_reaches_the_feedback_record_with_file_line_and_rule(tmp_path, path_with):
    import json
    from factory_engine.rework import build_feedback
    stub(path_with, "ruff", "echo 'app.py:4:1: F401 `os` imported but unused'; exit 1")
    w = fixture(tmp_path, {"pyproject.toml": "[project]\n", "app.py": "import os\n"})
    res = toolchains.check_lint_clean(GateSpec(kind="check", cmd=None, check="lint-clean", schema=None, args={}), ctx(w))
    assert not res.passed
    path = build_feedback(tmp_path / "run", from_stage="verify", to_stage="fix", result=res, loop=1, max_loops=2,
                          task_ids=["backend"])
    doc = json.loads(path.read_text())
    assert doc["gate"] == "lint-clean" and "app.py:4: F401" in doc["output_tail"]


def test_clean_lint_passes(tmp_path, path_with):
    stub(path_with, "ruff", "exit 0")
    w = fixture(tmp_path, {"pyproject.toml": "[project]\n", "app.py": "x = 1\n"})
    res = toolchains.check_lint_clean(GateSpec(kind="check", cmd=None, check="lint-clean", schema=None, args={}), ctx(w))
    assert res.passed


def test_parse_findings_reads_the_ruff_and_the_generic_form(tmp_path):
    tc = toolchains.Toolchain("python", "ruff", [], {}, tmp_path)
    out = "app.py:4:1: F401 unused\nsrc/x.ts:9: missing semicolon\nnoise line"
    f = toolchains.parse_findings(tc, out)
    assert [(x.file, x.line, x.rule) for x in f] == [("app.py", 4, "F401"), ("src/x.ts", 9, "lint")]


# ---- verify: one test task per language, parallel ----

def test_a_java_and_typescript_repo_gets_one_test_task_per_language_with_no_dependencies(tmp_path):
    w = fixture(tmp_path, {"pom.xml": "<project/>", "package.json": "{}"})
    tasks = toolchains.language_tasks(w, CFG, "test", ["src/A.java", "web/app.ts"])
    assert sorted(t.id for t in tasks) == ["test-java", "test-typescript"]
    assert all(t.needs == [] for t in tasks)  # parallel: no task waits for another


def test_only_the_languages_with_changed_files_get_a_test_task(tmp_path):
    """D5 (owner decision 2026-11-22): a run that changed only Python does not run the Java tests."""
    w = fixture(tmp_path, {"pom.xml": "<project/>", "pyproject.toml": "[project]\n"})
    assert [t.id for t in toolchains.language_tasks(w, CFG, "test", ["tools/gen.py"])] == ["test-python"]
    assert [t.id for t in toolchains.language_tasks(w, CFG, "test", ["a.py", "src/main/A.java"])] == ["test-java", "test-python"]
    assert toolchains.language_tasks(w, CFG, "test", ["README.md"]) == []        # no profile owns a .md file
    assert toolchains.language_tasks(w, CFG, "test", []) == []


def test_a_language_with_no_test_step_gets_no_task(tmp_path):
    w = fixture(tmp_path, {"pom.xml": "<project/>"})
    assert toolchains.language_tasks(w, CFG, "nonexistent-step", ["A.java"]) == []


def test_checkpoint_format_is_the_engines_step_and_not_the_workers(tmp_path):
    """module 17A: the engine formats once after a worker stops; a checkpoint is a git commit and runs no formatter.
    The checkpoint code path (module 7) never calls run_step, so this is checked by the source, not by a run."""
    src = Path(toolchains.__file__).parents[0] / "gitops.py"
    assert "run_step" not in src.read_text()


def test_doctor_reports_a_missing_tool_before_any_run(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    w = fixture(tmp_path, {"pom.xml": "<project/>"})
    results = {r.name: r for r in toolchains.doctor_checks(w, CFG)}
    mvn = results["toolchain:java:mvn"]
    assert not mvn.ok and "install mvn" in mvn.hint


def test_doctor_is_silent_about_tools_that_are_present(tmp_path, path_with):
    stub(path_with, "mvn")
    w = fixture(tmp_path, {"pom.xml": "<project/>"})
    assert all(r.ok for r in toolchains.doctor_checks(w, CFG) if r.name == "toolchain:java:mvn")


# ---- D8 (owner decision 2026-11-22): format the task's changed files once, after the worker has stopped ----

def _formatter(path_with, body):
    stub(path_with, "ruff", body)


def test_format_changed_files_runs_each_profile_on_its_own_files_only(tmp_path, path_with):
    w = fixture(tmp_path, {"pyproject.toml": "[project]\n", "go.mod": "module x\n", "a.py": "x=1\n", "sub/b.py": "y=2\n",
                           "m.go": "package m\n", "notes.txt": "keep\n"})
    _formatter(path_with, 'shift; for f in "$@"; do echo formatted > "$f"; done')
    stub(path_with, "gofmt", "exit 0")
    results = toolchains.format_changed_files(w, CFG, ["a.py", "sub/b.py", "notes.txt", "gone.py"], log_dir=tmp_path / "logs")
    assert [(r.step, r.ok) for r in results] == [("format", True)]
    assert (w / "a.py").read_text() == "formatted\n" and (w / "sub/b.py").read_text() == "formatted\n"
    assert (w / "notes.txt").read_text() == "keep\n"            # no profile owns a .txt file
    assert (w / "m.go").read_text() == "package m\n"            # the go profile had no changed file


def test_a_build_tool_formatter_runs_once_with_no_file_arguments(tmp_path, path_with):
    w = fixture(tmp_path, {"pom.xml": "<project/>", "src/A.java": "class A{}\n"})
    stub(path_with, "mvn", 'echo "$@" > mvn.args')          # the formatter runs in the worktree, so its record stays there
    toolchains.format_changed_files(w, CFG, ["src/A.java"], log_dir=tmp_path / "logs")
    assert (w / "mvn.args").read_text().strip() == "-q spotless:apply"   # a file name would be read as a phase


def test_a_formatter_that_exits_non_zero_is_reported_not_raised(tmp_path, path_with):
    w = fixture(tmp_path, {"pyproject.toml": "[project]\n", "a.py": "x=1\n"})
    _formatter(path_with, "echo boom; exit 2")
    [r] = toolchains.format_changed_files(w, CFG, ["a.py"], log_dir=tmp_path / "logs")
    assert not r.ok and r.exit_code == 2 and "boom" in r.output_tail


def test_a_missing_formatter_fails_fast_with_its_name(tmp_path, monkeypatch):
    w = fixture(tmp_path, {"pyproject.toml": "[project]\n", "a.py": "x=1\n"})
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(FactoryError) as e:
        toolchains.format_changed_files(w, CFG, ["a.py"], log_dir=tmp_path / "logs")
    assert "ruff" in e.value.message


def test_a_gradle_wrapper_in_the_repo_is_found_and_formatting_runs_it(tmp_path, monkeypatch):
    """`gradlew` is the repo's own script, not a program on PATH. srt must still be on PATH for the step to run."""
    w = fixture(tmp_path, {"build.gradle": "apply plugin: 'java'", "src/A.java": "class A{}\n"})
    wrapper = w / "gradlew"
    wrapper.write_text('#!/bin/sh\necho "$@" > gradle.args\n')
    wrapper.chmod(0o755)
    srt_dir = os.path.dirname(sandbox.srt_bin() or "/usr/bin/false")
    monkeypatch.setenv("PATH", f"{srt_dir}{os.pathsep}/usr/bin:/bin")
    [r] = toolchains.format_changed_files(w, CFG, ["src/A.java"], log_dir=tmp_path / "logs")
    assert r.ok and (w / "gradle.args").read_text().strip() == "spotlessApply"
    assert [c.ok for c in toolchains.doctor_checks(w, CFG) if c.name.endswith(":gradlew")] == [True]


def test_a_renamed_file_lists_its_new_path_and_not_its_old_path_or_a_cut_one(tmp_path):
    import subprocess
    from factory_engine import gitops
    w = tmp_path / "wt"
    w.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "a@b"], ["config", "user.name", "a"]):
        subprocess.run(["git", "-C", str(w), *args], check=True)
    (w / "src").mkdir()
    (w / "src" / "old.py").write_text("x=1\n")
    subprocess.run(["git", "-C", str(w), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(w), "commit", "-q", "--no-verify", "-m", "base"], check=True)
    subprocess.run(["git", "-C", str(w), "mv", "src/old.py", "src/new_name.py"], check=True)
    (w / "fresh.py").write_text("y=2\n")
    assert gitops.task_changed_files(w, None) == ["fresh.py", "src/new_name.py"]


# ---- item 2 (owner answer, 2026-11-22): formatter and lint steps run under srt, like cmd tasks and gate commands ----

from factory_engine.adapters.worker import sandbox  # noqa: E402

needs_srt = pytest.mark.skipif(sandbox.srt_bin() is None or (sandbox.node_version() or (0, 0))[:2] < (22, 12),
                               reason="srt 0.0.83 and Node 22.12 or later are needed")


@needs_srt
def test_a_formatter_cannot_write_outside_the_worktree_under_srt(tmp_path, path_with):
    """The formatter stub tries to write a file outside the worktree. Under srt the write is refused, so the step fails."""
    w = fixture(tmp_path, {"pyproject.toml": "[project]\n", "a.py": "x=1\n"})
    outside = tmp_path / "escaped.txt"
    stub(path_with, "ruff", f'if [ "$1" = format ]; then echo leaked > "{outside}"; fi; exit 0')
    [r] = toolchains.format_changed_files(w, CFG, ["a.py"], log_dir=tmp_path / "logs")
    assert not outside.exists(), "a sandboxed formatter wrote outside the worktree"


@needs_srt
def test_a_formatter_can_still_format_its_own_files_under_srt(tmp_path, path_with):
    w = fixture(tmp_path, {"pyproject.toml": "[project]\n", "a.py": "x=1\n"})
    stub(path_with, "ruff", 'if [ "$1" = format ]; then shift; for f in "$@"; do echo formatted > "$f"; done; fi; exit 0')
    [r] = toolchains.format_changed_files(w, CFG, ["a.py"], log_dir=tmp_path / "logs")
    assert r.ok and (w / "a.py").read_text() == "formatted\n"


# ---- item 58 (owner correction, 2026-11-25): the TypeScript test step writes a JUnit report; the others are unchanged ----

def test_the_typescript_test_step_is_a_node_argv_that_points_jest_junit_at_the_task_folder(tmp_path):
    """Commands run with no shell, so $FACTORY_TASK_DIR is not expanded in an argv. The step is `node -e`, which reads
    the variable the CommandAdapter sets for a cmd task and hands jest-junit its output path."""
    w = fixture(tmp_path, {"package.json": "{}"})
    argv = toolchains.detect(w, CFG)[0].commands["test"]
    assert argv[:2] == ["node", "-e"]
    assert "FACTORY_TASK_DIR" in argv[2] and "JEST_JUNIT_OUTPUT_FILE" in argv[2]
    assert "--reporters=jest-junit" in argv[2] and "'npm'" in argv[2]


def test_the_python_test_step_is_a_python_argv_that_points_pytest_at_the_task_folder(tmp_path):
    w = fixture(tmp_path, {"pyproject.toml": "[project]\n"})
    argv = toolchains.detect(w, CFG)[0].commands["test"]
    assert argv[:2] == ["python3", "-c"]
    assert "FACTORY_TASK_DIR" in argv[2] and "--junitxml=" in argv[2] and "test.junit.xml" in argv[2]


def test_the_maven_test_step_is_a_python_argv_that_runs_mvn_and_copies_the_surefire_reports_to_the_task_folder(tmp_path):
    w = fixture(tmp_path, {"pom.xml": "<project/>"})
    argv = toolchains.detect(w, CFG)[0].commands["test"]
    assert argv[:2] == ["python3", "-c"]
    assert "FACTORY_TASK_DIR" in argv[2] and "surefire-reports" in argv[2] and ".junit.xml" in argv[2]
    assert "'mvn','-q','test'" in argv[2].replace(" ", "")


def test_the_gradle_test_step_keeps_its_shipped_argv_because_it_was_not_verified(tmp_path):
    w = fixture(tmp_path, {"build.gradle": ""})
    assert toolchains.detect(w, CFG)[0].commands["test"] == ["gradlew", "test"]


def test_the_go_test_step_is_a_python_argv_that_runs_go_test_json_and_writes_a_junit_file(tmp_path):
    w = fixture(tmp_path, {"go.mod": "module x\n"})
    argv = toolchains.detect(w, CFG)[0].commands["test"]
    assert argv[:2] == ["python3", "-c"]
    assert "FACTORY_TASK_DIR" in argv[2] and "'-json'" in argv[2] and "test.junit.xml" in argv[2]
