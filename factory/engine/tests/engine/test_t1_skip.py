"""T1: `factory skip <run> --gate no-test-results` passes the no-test-results block for a repo with no tests, and only
that block (module 8; ADR 2026-11-17-t1-skip-is-a-named-block-skip)."""

import pytest

from factory_engine import api, delivery, state
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, failed, ok
from factory_engine.engine import Engine
from factory_engine.errors import FactoryError

from engine_helpers import TRIAGE_JSON
from test_verify_report import JUNIT_TWO_PASS, VERIFY_ONLY


def _run_verify(new_run, repo, cfg, tracker, prs, clock, junit: str, be=None):
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))], "be": be or [ok(work("be", "be.junit.xml"))],
              "fe": [ok(work("fe", "fe.junit.xml"))]}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "be": {"be.junit.xml": junit}, "fe": {"fe.junit.xml": junit}}
    command = FakeWorkerAdapter(script, writes=writes)
    eng = Engine(repo, cfg, workers={"claude": FakeWorkerAdapter({})}, command=command, tracker=tracker, prs=prs,
                 clock=clock)
    wf_dir = repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "chore.yaml").write_text(VERIFY_ONLY)
    eng.run(["bump-q1w2e"])
    assert state.read_run(run_dir).status == "blocked"
    return run_dir, eng


def test_a_skip_passes_the_zero_test_block_for_a_repo_with_no_tests(new_run, repo, cfg, tracker, prs, clock):
    run_dir, eng = _run_verify(new_run, repo, cfg, tracker, prs, clock, "<testsuite/>")
    assert state.read_run(run_dir).attention.command == 'factory skip bump-q1w2e --gate no-test-results --reason "..."'

    api.skip(repo, "bump-q1w2e", "no-test-results", reason="repo has no tests yet")

    assert state.read_run(run_dir).status != "blocked"
    skipped = [ev.data for ev in state.read_events(run_dir) if ev.type == "gate_skipped"]
    assert skipped == [{"stage": "verify", "gate": "no-test-results", "reason": "repo has no tests yet", "by": "cli"}]
    rule = next(r for r in delivery.evaluate_merge(run_dir, eng.cfg, changed=[], ci="green").rules
                if r.rule == "auto.require.gates")
    assert rule.passed is False


def test_the_t1_skip_is_refused_when_the_run_is_blocked_by_anything_else(new_run, repo, cfg, tracker, prs, clock):
    """Failing tests (the test command exits non-zero) past the rework limit block the same stage; the T1 skip must not
    pass them."""
    run_dir, eng = _run_verify(new_run, repo, cfg, tracker, prs, clock, JUNIT_TWO_PASS, be=[failed()] * 4)
    with pytest.raises(FactoryError) as e:
        api.skip(repo, "bump-q1w2e", "no-test-results", reason="repo has no tests yet")
    assert e.value.code == "config.invalid" and "no test results" in e.value.message
    assert state.read_run(run_dir).status == "blocked"
    assert not [ev for ev in state.read_events(run_dir) if ev.type == "gate_skipped"]
