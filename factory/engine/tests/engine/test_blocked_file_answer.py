"""A blocked run answered in its decision file (module 11; owner decision 2026-11-24): each answer calls the routine the
command line uses (Engine.retry, goto, skip, stop) under the run lock. `tick` and `run` read the answer too.

Built on the T1 fixture in test_t1_skip: the run is blocked at verify by the no-test-results block, and the decision
file is written by hand here, because a real block writes none (module 11, line 214, not ticked)."""

from factory_engine import decisions, state

from test_t1_skip import _run_verify


def _blocked(new_run, repo, cfg, tracker, prs, clock):
    run_dir, eng = _run_verify(new_run, repo, cfg, tracker, prs, clock, "<testsuite/>")
    sha = decisions.request(run_dir, "verify", 1, kind="blocked")
    return run_dir, eng, sha


def _answer(run_dir, sha, choices, notes=""):
    decisions.record(run_dir, "verify", 1, packet_sha=sha, choices=choices, notes=notes, by="me", channel="cli")


def _events(run_dir, kind):
    return [ev.data for ev in state.read_events(run_dir) if ev.type == kind]


def _lock_is_free(run_dir) -> bool:
    """True when this process can take the run's lock now, which means no routine left it held."""
    try:
        state.release(state.acquire_lock(run_dir, "test"))
    except Exception:  # noqa: BLE001  a held lock raises state.locked
        return False
    return True


def test_a_goto_answer_sends_the_run_to_the_stage_it_names(new_run, repo, cfg, tracker, prs, clock):
    run_dir, eng, sha = _blocked(new_run, repo, cfg, tracker, prs, clock)
    _answer(run_dir, sha, {"D1": "goto", "D1.target": "verify"})

    eng.tick_answered_blocked(run_dir.name)

    run = state.read_run(run_dir)
    assert run.status == "running" and run.stage == "verify"
    assert [e["to_stage"] for e in _events(run_dir, "run_routed")] == ["verify"]
    assert _lock_is_free(run_dir)  # the routine took the lock and gave it back


def test_a_retry_answer_runs_the_blocked_stage_again(new_run, repo, cfg, tracker, prs, clock):
    run_dir, eng, sha = _blocked(new_run, repo, cfg, tracker, prs, clock)
    _answer(run_dir, sha, {"D1": "retry"})

    eng.tick_answered_blocked(run_dir.name)

    assert state.read_run(run_dir).status == "running"
    assert [(e["stage"], e["note"]) for e in _events(run_dir, "run_retried")] == [("verify", False)]


def test_a_skip_answer_passes_the_gate_it_names_with_its_reason(new_run, repo, cfg, tracker, prs, clock):
    run_dir, eng, sha = _blocked(new_run, repo, cfg, tracker, prs, clock)
    _answer(run_dir, sha, {"D1": "skip", "D1.gate": "no-test-results"}, notes="repo has no tests yet")

    eng.tick_answered_blocked(run_dir.name)

    assert state.read_run(run_dir).status != "blocked"
    assert [(e["gate"], e["reason"]) for e in _events(run_dir, "gate_skipped")] == [
        ("no-test-results", "repo has no tests yet")]


def test_an_abort_answer_ends_the_run_with_its_notes_as_the_reason(new_run, repo, cfg, tracker, prs, clock):
    run_dir, eng, sha = _blocked(new_run, repo, cfg, tracker, prs, clock)
    _answer(run_dir, sha, {"D1": "abort"}, notes="the request is out of date")

    eng.tick_answered_blocked(run_dir.name)

    assert state.read_run(run_dir).status == "aborted"
    assert [e["reason"] for e in _events(run_dir, "run_aborted")] == ["the request is out of date"]


def test_a_pending_file_does_nothing(new_run, repo, cfg, tracker, prs, clock):
    run_dir, eng, _ = _blocked(new_run, repo, cfg, tracker, prs, clock)
    before = state.read_events(run_dir)

    eng.tick_answered_blocked(run_dir.name)

    assert state.read_run(run_dir).status == "blocked"
    assert state.read_events(run_dir) == before
    assert state.lock_status(run_dir) == "free"


def test_a_blocked_run_with_no_decision_file_does_nothing(new_run, repo, cfg, tracker, prs, clock):
    run_dir, eng = _run_verify(new_run, repo, cfg, tracker, prs, clock, "<testsuite/>")

    eng.tick_answered_blocked(run_dir.name)

    assert state.read_run(run_dir).status == "blocked"


def test_an_answer_in_the_file_of_a_run_that_is_not_blocked_is_not_read(new_run, repo, cfg, tracker, prs, clock):
    run_dir, eng, sha = _blocked(new_run, repo, cfg, tracker, prs, clock)
    _answer(run_dir, sha, {"D1": "abort"})
    lock = state.acquire_lock(run_dir, "test")
    run = state.read_run(run_dir)
    run.status = "running"
    state.write_run(run_dir, run, lock=lock)
    state.release(lock)

    eng.tick_answered_blocked(run_dir.name)

    assert state.read_run(run_dir).status == "running"


def test_a_refused_answer_leaves_the_run_blocked_and_the_file_open_for_a_new_answer(
        new_run, repo, cfg, tracker, prs, clock):
    """A goto to a stage the workflow does not have is refused by Engine.goto. It must not raise out of the pass (that
    would stop `factory run` for every run), and the same answer must not be read again on each pass."""
    run_dir, eng, sha = _blocked(new_run, repo, cfg, tracker, prs, clock)
    _answer(run_dir, sha, {"D1": "goto", "D1.target": "no-such-stage"})

    eng.tick_answered_blocked(run_dir.name)

    assert state.read_run(run_dir).status == "blocked"
    assert [e["code"] for e in _events(run_dir, "blocked_answer_refused")] == ["config.invalid"]
    assert decisions.read_decision(run_dir, "verify", 1)["decision"]["status"] == "pending"


def test_tick_applies_a_blocked_answer(new_run, repo, cfg, tracker, prs, clock):
    """Engine.tick runs one pass for one run under its lock. The launcher's `factory tick` does not call it: it starts
    `factory run`, and it starts that only for an answered awaiting_approval run (launcher tick.decide)."""
    run_dir, eng, sha = _blocked(new_run, repo, cfg, tracker, prs, clock)
    _answer(run_dir, sha, {"D1": "abort"})

    eng.tick(run_dir.name)

    assert state.read_run(run_dir).status == "aborted"
    assert state.lock_status(run_dir) == "free"


def test_run_applies_a_blocked_answer_and_reports_the_new_status(new_run, repo, cfg, tracker, prs, clock):
    """Engine.run is what `factory run` calls: _drive holds the lock across its passes and must hand it to the routine."""
    run_dir, eng, sha = _blocked(new_run, repo, cfg, tracker, prs, clock)
    _answer(run_dir, sha, {"D1": "abort"})

    result = eng.run([run_dir.name])

    assert result.runs == {run_dir.name: "aborted"}
    assert state.lock_status(run_dir) == "free"
