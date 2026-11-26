"""Module 10, practice packs in a skill task's context: each language the run changed gets its pack, chosen by 17A's
detect and file match (the verify wiring's computation, not a second detector). A pack is a pointer, never text, and a
task whose run changed no tested language gets none. Only Python has a shipped pack, so the Java and TypeScript cases
run against a temporary kit with fake packs for those two languages."""

import os
import shutil
import stat
from pathlib import Path

import pytest

from factory_engine import skills
from factory_engine.adapters.worker.fake import ok

from engine_helpers import TRIAGE_JSON

KIT = Path(__file__).resolve().parents[3]  # factory/
JUNIT_TWO = '<testsuite><testcase name="a"/><testcase name="b"/></testsuite>'

WORKFLOW = """name: chore
type: chore
sink: pull_request
policy: {write: true, deny_paths: [".github/**"]}
defaults: {retries: 0, timeout_minutes: 5, checkpoint_every_minutes: 10, max_restarts: 0}
stages:
  - id: implement
    tasks: [{id: change, skill: implement, scope: ["**"], helpers: {mode: off}, out: change.json}]
  - id: verify
    needs: [implement]
    tasks_from: languages
  - id: polish
    needs: [verify]
    tasks: [{id: polish, skill: fix, scope: ["**"], helpers: {mode: off}, out: polish.json}]
"""

JAVA_AND_TS = {"pom.xml": "<project/>", "src/main/A.java": "class A {}\n",
               "package.json": "{}", "web/app.ts": "export const a = 1;\n"}


@pytest.fixture(autouse=True)
def formatters(tmp_path, monkeypatch):
    """The implement stage formats the worker's files with each profile's own formatter. These tests are about the
    pack, so stub `ruff`, `mvn` and `npx` stand in for the real ones."""
    bins = tmp_path / "bin"
    bins.mkdir()
    for name in ("mvn", "npx", "ruff"):
        p = bins / name
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bins}{os.pathsep}{os.environ['PATH']}")


@pytest.fixture
def fake_kit(tmp_path):
    """A copy of the shipped kit with fake Java and TypeScript packs, so the mixed-language case has two packs."""
    kit = tmp_path / "kit"
    shutil.copytree(KIT, kit, ignore=shutil.ignore_patterns(".venv", "__pycache__", "tests", "engine", "dashboard"))
    for lang in ("java", "typescript"):
        d = kit / "skills" / "own" / "practices" / lang
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: practices-{lang}\ndescription: fake {lang} pack\n---\n{lang} rules\n")
    skills.use_kit(kit)
    return kit


def _pack_of(worker, task_id):
    """The practice packs the fake worker was given for one task, as the engine built its context."""
    contexts = [c for c in worker.started if c.task_id == task_id]
    assert len(contexts) == 1, f"{task_id} started {len(contexts)} times"
    return contexts[0].practices


def _run(new_run, engine, files):
    """Runs implement (writing `files` into its worktree), the verify test tasks, then polish. Polish is the skill
    task under test: it starts after the run's changes are on the run branch."""
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))], "change": [ok(work("change", "change.json"))],
              "polish": [ok(work("polish", "polish.json"))]}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "change": {"change.json": "{}"}, "polish": {"polish.json": "{}"}}
    for task in ("test-java", "test-python", "test-typescript"):
        script[task] = [ok(work(task, "test.junit.xml"))]
        writes[task] = {"test.junit.xml": JUNIT_TWO}
    eng, worker = engine(script, writes)
    real_start = worker.start

    def start(ctx, conf, log):
        if ctx.task_id == "change":
            for rel, text in files.items():
                (ctx.worktree / rel).parent.mkdir(parents=True, exist_ok=True)
                (ctx.worktree / rel).write_text(text)
        return real_start(ctx, conf, log)

    worker.start = start
    wf_dir = eng.repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "chore.yaml").write_text(WORKFLOW)
    eng.run(["bump-q1w2e"])
    return worker


def test_a_python_only_task_gets_the_python_pack_and_no_other(new_run, engine):
    worker = _run(new_run, engine, {"pyproject.toml": "[project]\nname = 'p'\n", "services/api.py": "x = 2\n"})
    packs = _pack_of(worker, "polish")
    assert [p.name for p in packs] == ["practices-python"]
    assert packs[0].source == "own"
    assert packs[0].path == KIT / "skills" / "own" / "practices" / "python"


def test_a_task_that_changed_java_and_typescript_gets_both_packs(new_run, engine, fake_kit):
    worker = _run(new_run, engine, JAVA_AND_TS)
    assert [p.name for p in _pack_of(worker, "polish")] == ["practices-java", "practices-typescript"]


def test_a_java_only_task_gets_only_the_java_pack(new_run, engine, fake_kit):
    worker = _run(new_run, engine, {"pom.xml": "<project/>", "src/main/A.java": "class A {}\n"})
    assert [p.name for p in _pack_of(worker, "polish")] == ["practices-java"]


def test_a_task_with_no_detected_language_gets_no_pack(new_run, engine):
    worker = _run(new_run, engine, {"notes.txt": "hello\n"})
    assert _pack_of(worker, "polish") == []


def test_a_test_task_is_a_command_and_gets_no_pack(new_run, engine):
    worker = _run(new_run, engine, {"pyproject.toml": "[project]\nname = 'p'\n", "services/api.py": "x = 2\n"})
    assert [c.task_id for c in worker.started if c.task_id.startswith("test-")] == ["test-python"]
    assert _pack_of(worker, "test-python") == []
