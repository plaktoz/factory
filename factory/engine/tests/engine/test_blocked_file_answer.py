"""A blocked run answered in its decision file (module 11; owner decision 2026-11-24): a goto or skip answer, with its
target, calls the same routine the command line uses (api.goto, api.skip). Built on the T1 fixture in test_t1_skip."""

from factory_engine import decisions, state

from test_t1_skip import _run_verify


def test_a_goto_answer_in_the_blocked_file_sends_the_run_to_its_stage(new_run, repo, cfg, tracker, prs, clock):
    run_dir, eng = _run_verify(new_run, repo, cfg, tracker, prs, clock, "<testsuite/>")
    sha = decisions.request(run_dir, "verify", 1, kind="blocked")
    decisions.record(run_dir, "verify", 1, packet_sha=sha, choices={"D1": "goto", "D1.target": "verify"},
                     by="me", channel="cli")

    eng.tick_answered_blocked(run_dir.name)  # the routine the file answer is read by

    assert state.read_run(run_dir).status != "blocked"
