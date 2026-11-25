"""Item 58, verify wiring (module 17A, "Verify wiring"): a stage with `tasks_from: languages` gets one test task for each
language the run changed, from the project's language profiles. Each writes its JUnit file into its task folder, and
the stage's {schema: test-report} gate reads them. A changed file no test task covers is reported, not skipped silently."""

import json
import os
import stat

import pytest

from factory_engine import state
from factory_engine.adapters.worker.fake import ok

from engine_helpers import TRIAGE_JSON


@pytest.fixture(autouse=True)
def formatters(tmp_path, monkeypatch):
    """The implement stage formats the worker's files with each profile's own formatter (module 17A). These tests are
    about verify, so a stub `mvn`, `npx` and `ruff` that do nothing stand in for the real ones."""
    bins = tmp_path / "bin"
    bins.mkdir()
    for name in ("mvn", "npx", "ruff"):
        p = bins / name
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bins}{os.pathsep}{os.environ['PATH']}")

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
    gate: [{schema: test-report}]
    on_fail: {goto: implement, max: 2}
"""


def _change_writes(worker, files):
    """The `change` worker writes the product files into its task worktree, so the implement join commits them."""
    real_start = worker.start

    def start(ctx, conf, log):
        if ctx.task_id == "change":
            for rel, text in files.items():
                (ctx.worktree / rel).parent.mkdir(parents=True, exist_ok=True)
                (ctx.worktree / rel).write_text(text)
        return real_start(ctx, conf, log)

    worker.start = start


def _run(new_run, engine, files, test_tasks):
    """Runs implement (writing `files`) then verify, with a scripted test task for each name in `test_tasks`."""
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))], "change": [ok(work("change", "change.json"))]}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "change": {"change.json": "{}"}}
    for task in test_tasks:
        script[task] = [ok(work(task, "test.junit.xml"))]
        writes[task] = {"test.junit.xml": JUNIT_TWO}
    eng, worker = engine(script, writes)
    _change_writes(worker, files)
    wf_dir = eng.repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "chore.yaml").write_text(WORKFLOW)
    eng.run(["bump-q1w2e"])
    return run_dir, worker


def _events(run_dir, kind):
    return [e.data for e in state.read_events(run_dir) if e.type == kind]


JAVA_AND_TS = {"pom.xml": "<project/>", "src/main/A.java": "class A {}\n",
               "package.json": "{}", "web/app.ts": "export const a = 1;\n"}


def test_a_repo_changed_in_two_languages_gets_one_test_task_for_each_and_the_report_gate_passes(new_run, engine):
    run_dir, worker = _run(new_run, engine, JAVA_AND_TS, test_tasks=("test-java", "test-typescript"))
    assert sorted(c.task_id for c in worker.started if c.task_id.startswith("test-")) == ["test-java", "test-typescript"]
    run = state.read_run(run_dir)
    assert run.status != "blocked"
    assert [state.read_task(run_dir, t).status for t in ("test-java", "test-typescript")] == ["done", "done"]
    assert json.loads((run_dir / "test-report.json").read_text()) == {"schema_version": 1, "total": 4, "failed": []}


def test_only_the_language_the_run_changed_gets_a_test_task(new_run, engine):
    run_dir, worker = _run(new_run, engine, {"pyproject.toml": "[project]\nname = 'p'\n", "services/api.py": "x = 2\n"},
                           test_tasks=("test-python",))
    assert sorted(c.task_id for c in worker.started if c.task_id.startswith("test-")) == ["test-python"]
    assert state.read_run(run_dir).status != "blocked"


def test_a_changed_file_no_test_task_covers_is_reported_not_skipped(new_run, engine):
    """A Rust file in a repo with Java and TypeScript: the two test tasks run, and the Rust file is named in the
    verify event, so a reader can see that nothing tested it."""
    run_dir, _ = _run(new_run, engine, {**JAVA_AND_TS, "src/main.rs": "fn main() {}\n"},
                      test_tasks=("test-java", "test-typescript"))
    reported = _events(run_dir, "verify_languages")
    assert len(reported) == 1
    assert reported[0]["tasks"] == ["test-java", "test-typescript"]
    assert reported[0]["uncovered"] == ["src/main.rs"]


def test_the_list_is_fixed_when_verify_starts_and_a_later_change_does_not_alter_it(new_run, engine):
    """A worker that edits another language's file after verify has started does not add a task to verify: the list
    is decided once, when the stage starts, so the stage cannot change under its own tasks (module 17A)."""
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))], "change": [ok(work("change", "change.json"))],
              "test-python": [ok(work("test-python", "test.junit.xml"))]}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "change": {"change.json": "{}"},
              "test-python": {"test.junit.xml": JUNIT_TWO}}
    eng, worker = engine(script, writes)
    _change_writes(worker, {"pyproject.toml": "[project]\nname = 'p'\n", "services/api.py": "x = 2\n"})
    wf_dir = eng.repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "chore.yaml").write_text(WORKFLOW)
    frozen = []
    real_start = worker.start

    def start(ctx, conf, log):
        if ctx.task_id == "test-python" and not frozen:
            frozen.append(json.loads((run_dir / "languages.json").read_text()))
            (ctx.worktree / "package.json").write_text("{}")  # a later change in another language
        return real_start(ctx, conf, log)

    worker.start = start
    eng.run(["bump-q1w2e"])
    assert frozen == [[{"id": "test-python", "cmd": frozen[0][0]["cmd"], "scope": [], "deny": [], "needs": [],
                        "helpers": {"mode": "off", "max": 0, "split_hints": [], "timeout_minutes": None},
                        "out": "test.junit.xml", "timeout_minutes": 30, "retries": 0, "max_interruptions": 3,
                        "network_domains": []}]]
    assert sorted(c.task_id for c in worker.started if c.task_id.startswith("test-")) == ["test-python"]


def test_a_run_that_changed_no_tested_language_still_blocks_on_zero_test_cases(new_run, engine):
    """T1 (module 8) keeps its meaning: no test task means no test cases, so the run blocks and no pull request opens."""
    run_dir, _ = _run(new_run, engine, {"notes.txt": "hello\n"}, test_tasks=())
    run = state.read_run(run_dir)
    assert run.status == "blocked"
    assert run.attention is not None and "no test results" in run.attention.summary
    assert any(e["code"] == "gate.no_test_results" for e in _events(run_dir, "gate_failed"))
