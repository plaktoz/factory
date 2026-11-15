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
    toolchains.run_step(toolchains.detect(w, CFG)[0], "test", w, log=log)
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
    tasks = toolchains.language_tasks(w, CFG, "test")
    assert sorted(t.id for t in tasks) == ["test-java", "test-typescript"]
    assert all(t.needs == [] for t in tasks)  # parallel: no task waits for another


def test_a_language_with_no_test_step_gets_no_task(tmp_path):
    w = fixture(tmp_path, {"pom.xml": "<project/>"})
    assert toolchains.language_tasks(w, CFG, "nonexistent-step") == []


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
