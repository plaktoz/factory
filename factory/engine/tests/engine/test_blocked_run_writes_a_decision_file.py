"""Module 11, every stop kind: a run that the engine blocks writes a decision file that offers retry, goto, skip and abort
(module 8, "When a run is blocked, its decision file offers these options"). The engine logs `run_blocked` and writes the
blocked file at the stage the run is on and its open visit, in the same pass and under the same lock."""

from factory_engine import decisions as D
from factory_engine import state

from test_max_interruptions import _chore, _cut_off_n_times
from test_t1_skip import _run_verify


def _events(run_dir, kind):
    return [ev.data for ev in state.read_events(run_dir) if ev.type == kind]


def test_a_run_the_engine_blocks_writes_a_decision_file_with_the_four_blocked_options(new_run, engine):
    run_dir, eng, _ = _chore(new_run, engine, attempts=4)
    _cut_off_n_times(eng, "bump-q1w2e", 3)
    eng.resume("bump-q1w2e")
    run = state.read_run(run_dir)
    assert run.status == "blocked"
    doc = D.read_decision(run_dir, run.stage, D.latest_visit(run, run.stage))
    assert {o["id"] for o in doc["packet"]["decisions"][0]["options"]} == D.BLOCKED_OPTIONS


def test_the_block_file_is_pending_and_is_the_file_for_the_stage_and_visit_the_block_logs(new_run, engine):
    run_dir, eng, _ = _chore(new_run, engine, attempts=4)
    _cut_off_n_times(eng, "bump-q1w2e", 3)
    eng.resume("bump-q1w2e")
    run = state.read_run(run_dir)
    visit = D.latest_visit(run, run.stage)
    assert [e["stage"] for e in _events(run_dir, "run_blocked")] == [run.stage]
    assert D.read_decision(run_dir, run.stage, visit)["decision"]["status"] == "pending"
    assert [(e["stage"], e["visit"], e["kind"]) for e in _events(run_dir, "decision_requested")] == [(run.stage, visit, "blocked")]
    assert [e["kind"] for e in _events(run_dir, "attention_requested")] == ["blocked"]


def test_a_triage_block_with_no_workflow_to_retry_writes_no_blocked_file(new_run, engine, monkeypatch):
    """Triage can block a run with fewer than two loadable workflows. That run has no workflow, so retry, goto, skip and
    abort cannot apply to it and no blocked file is written (module 11, "A blocked run's answer")."""
    from test_engine import _triage_that_cannot_decide
    from factory_engine import decisions as D

    run_dir, eng = _triage_that_cannot_decide(new_run, engine)
    monkeypatch.setattr(eng, "_loads", lambda wid: wid == "chore")
    eng.run(["bump-q1w2e"])
    assert state.read_run(run_dir).status == "blocked"
    assert [e["stage"] for e in _events(run_dir, "run_blocked")] == ["triage"]
    assert not D.decision_path(run_dir, "triage", 1).exists()


def test_a_block_with_no_stage_to_name_writes_no_file_and_still_logs_the_block(new_run, repo, cfg, tracker, prs, clock):
    """A block can reach a run with no stage to name (a skip of the last stage leaves run.stage empty). The block is
    logged, but no decision file is written under an empty stage name."""
    from factory_engine import rework
    from factory_engine.engine import Engine

    run_dir, _ = _run_verify(new_run, repo, cfg, tracker, prs, clock, "<testsuite/>")
    before = sorted(p.name for p in (run_dir / "decisions").iterdir())
    run = state.read_run(run_dir)
    run.stage = ""
    Engine._record_block(run, run_dir, rework.Routing("blocked", reason="delivery is down"))

    assert [e["stage"] for e in _events(run_dir, "run_blocked")][-1] == ""
    assert sorted(p.name for p in (run_dir / "decisions").iterdir()) == before


def test_a_block_after_an_answer_was_applied_asks_again_instead_of_keeping_the_old_answer(new_run, repo, cfg, tracker, prs, clock):
    """Retry leaves the visit as it was, so the run can block again at the same stage. The new block gets a pending file;
    the answer the earlier block applied is not kept, or the run would stay blocked with nothing to apply."""
    run_dir, eng = _run_verify(new_run, repo, cfg, tracker, prs, clock, "<testsuite/>")
    sha = D.read_decision(run_dir, "verify", 1)["packet"]["sha"]
    D.record(run_dir, "verify", 1, packet_sha=sha, choices={"D1": "retry"}, by="me", channel="cli")
    eng.tick_answered_blocked(run_dir.name)
    assert state.read_run(run_dir).status == "running"

    eng.resume("bump-q1w2e")  # the same empty test report blocks the run again

    assert state.read_run(run_dir).status == "blocked"
    assert D.read_decision(run_dir, "verify", 1)["decision"]["status"] == "pending"
    assert len(_events(run_dir, "run_blocked")) == 2
