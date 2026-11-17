"""T1 says `factory skip` passes the no-test-results block for a repo with no tests (decision T1, module 8). This
probe checks whether skip can reach that block. It is strict-xfail: it fails today because the T1 block is not a
skippable gate, and it will start to pass, and so fail the suite, once the owner's choice of how to mark it is built."""

import json

import pytest

from factory_engine import api, state
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
from factory_engine.engine import Engine

from conftest import TRIAGE_JSON
from test_verify_report import VERIFY_ONLY


@pytest.mark.xfail(strict=True, reason="T1's block is not a skippable gate, so factory skip cannot pass it (item 12)")
def test_a_skip_passes_the_zero_test_block_for_a_repo_with_no_tests(new_run, repo, cfg, tracker, prs, clock):
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))], "be": [ok(work("be", "be.junit.xml"))],
              "fe": [ok(work("fe", "fe.junit.xml"))]}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "be": {"be.junit.xml": "<testsuite/>"},
              "fe": {"fe.junit.xml": "<testsuite/>"}}
    command = FakeWorkerAdapter(script, writes=writes)
    eng = Engine(repo, cfg, workers={"claude": FakeWorkerAdapter({})}, command=command, tracker=tracker, prs=prs,
                 clock=clock)
    wf_dir = repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "chore.yaml").write_text(VERIFY_ONLY)
    eng.run(["bump-q1w2e"])
    assert state.read_run(run_dir).status == "blocked"

    api.skip(repo, "bump-q1w2e", "cmd: [make, test-api]", reason="repo has no tests yet")
    assert state.read_run(run_dir).status != "blocked"
