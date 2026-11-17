"""Item 12, gap 3, through the engine: a verify stage's join writes test-report.json from the stage's JUnit files, and
the {schema: test-report} gate reads it. Before the wiring, the gate read one task's .junit.xml as JSON and failed with
gate.schema, so no real run got past verify."""

import json

from factory_engine import state
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
from factory_engine.engine import Engine

from conftest import TRIAGE_JSON

JUNIT_TWO_PASS = '<testsuite><testcase name="a"/><testcase name="b"/></testsuite>'
JUNIT_ONE_FAIL = '<testsuite><testcase name="c"><failure/></testcase></testsuite>'

VERIFY_ONLY = """name: chore
type: chore
sink: pull_request
policy: {write: true, deny_paths: []}
defaults: {retries: 0, timeout_minutes: 5, checkpoint_every_minutes: 10, max_restarts: 0}
stages:
  - id: verify
    tasks:
      - {id: be, cmd: [make, test-api], out: be.junit.xml}
      - {id: fe, cmd: [npm, test], out: fe.junit.xml}
    join: all
    gate: [{schema: test-report}]
    on_fail: {goto: verify, max: 1}
"""


def _run_verify(new_run, repo, cfg, tracker, prs, clock, be_junit: str, fe_junit: str):
    """Triage picks `chore`, which this repo overrides with only a verify stage. The two cmd tasks go to the command
    adapter, which is a fake that writes their JUnit files."""
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))], "be": [ok(work("be", "be.junit.xml"))],
              "fe": [ok(work("fe", "fe.junit.xml"))]}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "be": {"be.junit.xml": be_junit}, "fe": {"fe.junit.xml": fe_junit}}
    command = FakeWorkerAdapter(script, writes=writes)
    eng = Engine(repo, cfg, workers={"claude": FakeWorkerAdapter({})}, command=command, tracker=tracker, prs=prs,
                 clock=clock)
    wf_dir = repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "chore.yaml").write_text(VERIFY_ONLY)
    eng.run(["bump-q1w2e"])
    return run_dir


def test_a_verify_join_writes_the_report_and_the_gate_passes_on_it(new_run, repo, cfg, tracker, prs, clock):
    run_dir = _run_verify(new_run, repo, cfg, tracker, prs, clock, JUNIT_TWO_PASS, JUNIT_TWO_PASS)
    assert json.loads((run_dir / "test-report.json").read_text()) == {"schema_version": 1, "total": 4, "failed": []}
    assert [s.status for s in state.read_run(run_dir).stages] == ["done", "done"]


def test_a_failing_verify_names_the_failed_test_in_the_report(new_run, repo, cfg, tracker, prs, clock):
    run_dir = _run_verify(new_run, repo, cfg, tracker, prs, clock, JUNIT_ONE_FAIL, JUNIT_TWO_PASS)
    report = json.loads((run_dir / "test-report.json").read_text())
    assert report["total"] == 3 and report["failed"] == ["c"]


def test_a_verify_stage_with_no_test_cases_blocks_the_run_and_names_the_missing_junit_files(new_run, repo, cfg, tracker,
                                                                                            prs, clock):
    """T1 (module 8, owner decision): a verify stage whose tasks report 0 test cases together blocks the run with a
    reason naming the missing JUnit files, and opens no pull request."""
    run_dir = _run_verify(new_run, repo, cfg, tracker, prs, clock, "<testsuite/>", "<testsuite/>")
    run = state.read_run(run_dir)
    assert run.status == "blocked"
    assert run.attention is not None and "be.junit.xml" in run.attention.summary
    assert prs.prs == {} and prs.calls == []
