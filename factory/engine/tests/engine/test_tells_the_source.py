"""Module 4 (status goes back to the source) and module 11 (the source is told at each human stop): the engine writes
the run's state to the request's source. A run from a GitHub issue moves the issue's status label; any other source
is not sent to the tracker."""

from engine_helpers import chore_script
from test_engine import _answer, _approve_implement

from factory_engine import state
from factory_engine.adapters.worker.fake import failed, ok
from factory_engine.types import Request, Source


def _request(source_type: str) -> Request:
    src = Source(source_type, "acme/report#1", "Bump the lint config", "Bump it.", ["chore"], "alice", [])
    return Request("gh-1", src, "sha1", "repo", "Bump the lint config", "chore", "explicit", None, [])


def _labels(tracker) -> list[str]:
    return [s.status for s in tracker.statuses]


def test_an_issue_run_is_marked_running_then_needs_human_at_a_stop_with_one_comment(new_run, engine, tracker):
    run_dir = new_run(_request("github"))
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    _approve_implement(eng)
    eng.run(["bump-q1w2e"])
    assert _labels(tracker) == ["factory:running", "factory:needs-human"]
    stop = tracker.statuses[-1]
    assert stop.ref == "acme/report#1" and "@alice" in stop.comment and "factory decide" in stop.comment
    eng.run(["bump-q1w2e"])                      # an engine that finds the stop still unanswered says nothing new
    assert _labels(tracker) == ["factory:running", "factory:needs-human"]


def test_an_answered_stop_puts_the_issue_back_to_running_and_a_merge_ends_it_done(new_run, engine, tracker):
    run_dir = new_run(_request("github"))
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    _approve_implement(eng)
    eng.run(["bump-q1w2e"])
    _answer(run_dir, "implement", "approve")
    eng.run(["bump-q1w2e"])
    assert _labels(tracker) == ["factory:running", "factory:needs-human", "factory:running", "factory:needs-human"]
    assert "pull request" in tracker.statuses[-1].comment.lower()      # the merge review is a stop too
    eng.prs.human_merge(state.read_run(run_dir).pr)
    eng.run(["bump-q1w2e"])
    assert _labels(tracker)[-1] == "factory:done"
    assert tracker.statuses[-1].comment and "done" in tracker.statuses[-1].comment.lower()


def test_a_blocked_run_marks_the_issue_blocked(new_run, engine, tracker):
    run_dir = new_run(_request("github"))
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * 4)
    eng, worker = engine(script, writes)
    real_start = worker.start

    def start(ctx, conf, log):
        if ctx.task_id == "change":
            bad = ctx.worktree / ".github" / "workflows"      # .github/** is in policy.deny_paths
            bad.mkdir(parents=True, exist_ok=True)
            (bad / "x.yml").write_text("bad")
        return real_start(ctx, conf, log)

    worker.start = start
    eng.run(["bump-q1w2e"])
    assert state.read_run(run_dir).status == "blocked"
    assert _labels(tracker) == ["factory:running", "factory:blocked"]
    assert "factory retry" in tracker.statuses[-1].comment


def test_a_failed_tracker_never_stops_the_run(new_run, engine, tracker, monkeypatch):
    from factory_engine import notify
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)
    run_dir = new_run(_request("github"))
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)

    def down(*a, **k):
        raise OSError("gh is down")

    tracker.set_status = down
    assert eng.run(["bump-q1w2e"]).runs == {"bump-q1w2e": "awaiting_approval"}   # it reached its pull request


def test_a_cli_request_is_never_sent_to_the_tracker(new_run, engine, tracker):
    run_dir = new_run(_request("cli"))
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    _approve_implement(eng)
    eng.run(["bump-q1w2e"])
    assert state.read_run(run_dir).attention is not None
    assert tracker.statuses == []


def test_a_tell_that_failed_is_tried_again_on_the_next_pass(new_run, engine, tracker, monkeypatch):
    from factory_engine import notify
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)
    run_dir = new_run(_request("github"))
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    _approve_implement(eng)
    real = tracker.set_status

    def down(*a, **k):
        raise OSError("gh is down")

    tracker.set_status = down
    eng.run(["bump-q1w2e"])                      # the run reaches its stop; neither label could be written
    assert tracker.statuses == [] and state.read_run(run_dir).status == "awaiting_approval"
    tracker.set_status = real
    eng.run(["bump-q1w2e"])                      # GitHub is back: the stop is told now, and once
    assert _labels(tracker) == ["factory:needs-human"]
    assert "@alice" in tracker.statuses[0].comment
    eng.run(["bump-q1w2e"])
    assert _labels(tracker) == ["factory:needs-human"]
