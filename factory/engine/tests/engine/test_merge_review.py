"""A run with a pull request waits at its merge review until GitHub merges or closes it (ADR 2026-11-20)."""

import pytest
from conftest import chore_script

from factory_engine import delivery, state
from factory_engine.errors import FactoryError
from factory_engine.types import Request, Source

RUN = "bump-q1w2e"


def github_request():
    """A request from a GitHub issue that alice opened, so she is the person asked to review. Built here, not imported
    from conftest: a full test run loads another folder's conftest under that name, and the import fails there."""
    src = Source("github", "acme/report#1", "Bump the lint config", "Bump it.", ["chore"], "alice", [])
    return Request("gh-1", src, "sha1", "repo", "Bump the lint config", "chore", "explicit", None, [])


@pytest.fixture
def parked(new_run, engine, prs):
    """A clean chore run from a GitHub issue, driven until it parks at its merge review. Returns the engine, run folder
    and pull request."""
    run_dir = new_run(request=github_request())
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    eng.run([RUN])
    return eng, run_dir, state.read_run(run_dir).pr


def test_a_run_with_a_pull_request_waits_for_review_and_is_not_done(parked):
    eng, run_dir, pr = parked
    run = state.read_run(run_dir)
    assert run.status == "awaiting_approval" and run.pr == pr
    assert run.attention is not None and run.attention.kind == "merge_review"
    assert delivery.at_merge_review(run)
    assert not any(e.type == "run_done" for e in state.read_events(run_dir))


def test_the_engine_exits_with_code_3_while_the_pull_request_is_open(new_run, engine):
    run_dir = new_run()
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    result = eng.run([RUN])
    assert result.runs == {RUN: "awaiting_approval"} and result.exit_code == 3


def test_an_open_pull_request_leaves_the_run_waiting_and_writes_nothing(parked, prs):
    eng, run_dir, pr = parked
    before = (run_dir / "run.json").read_text()
    events = len(state.read_events(run_dir))
    assert eng.run([RUN]).runs == {RUN: "awaiting_approval"}
    assert (run_dir / "run.json").read_text() == before
    assert len(state.read_events(run_dir)) == events
    assert prs.calls[-1] == "state"


def test_a_merged_pull_request_ends_the_run_done_and_removes_its_worktree(parked, prs):
    eng, run_dir, pr = parked
    worktree = state.read_run(run_dir).worktree
    assert worktree.exists()
    prs.human_merge(pr)
    assert eng.run([RUN]).runs == {RUN: "done"}
    run = state.read_run(run_dir)
    assert run.status == "done" and run.attention is None
    assert [e.type for e in state.read_events(run_dir)].count("merged") == 1
    assert any(e.type == "run_done" for e in state.read_events(run_dir))
    assert not worktree.exists()


def test_a_closed_pull_request_aborts_the_run(parked, prs):
    eng, run_dir, pr = parked
    prs.close(pr)
    assert eng.run([RUN]).runs == {RUN: "aborted"}
    assert state.read_run(run_dir).attention is None
    assert any(e.type == "run_aborted" for e in state.read_events(run_dir))


def test_red_ci_sends_the_run_back_with_the_failing_output_as_feedback(parked, prs):
    eng, run_dir, pr = parked
    prs.set_ci(pr, "red", "lint: FAILURE")
    eng.tick(RUN)
    run = state.read_run(run_dir)
    assert run.status == "running" and run.stage == "implement"
    assert run.loops == {"verify->implement:ci": 1}
    feedback = list((run_dir / "tasks" / "change" / "feedback").glob("*.json"))
    assert len(feedback) == 1 and "lint: FAILURE" in feedback[0].read_text()
    assert [e.type for e in state.read_events(run_dir)].count("routed_back") == 1


def test_a_red_run_that_gets_a_fix_returns_to_its_merge_review_and_pushes_the_fix(new_run, engine, prs, repo):
    import subprocess
    from factory_engine.adapters.worker.fake import ok
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * 2,
                                  check=[ok(work("check", "check.log"))] * 2)
    eng, worker = engine(script, writes)
    eng.run([RUN])
    pr = state.read_run(run_dir).pr
    first_push = subprocess.run(["git", "ls-remote", "origin", f"refs/heads/{RUN}"], cwd=repo, capture_output=True,
                                text=True, check=True).stdout.split()[0]
    real_start = worker.start
    seen = {"change": 0}

    def start(ctx, conf, log):
        if ctx.task_id == "change":
            seen["change"] += 1
            if seen["change"] == 1:  # the fix attempt: a real file, so the join makes a commit
                (ctx.worktree / "fix.txt").write_text("the fix\n")
        return real_start(ctx, conf, log)

    worker.start = start
    prs.set_ci(pr, "red", "lint: FAILURE")
    eng.tick(RUN)
    result = eng.run([RUN])
    run = state.read_run(run_dir)
    assert result.runs == {RUN: "awaiting_approval"}
    assert run.pr == pr and len(prs.prs) == 1       # the same pull request, not a second one
    assert delivery.at_merge_review(run)
    pushed = subprocess.run(["git", "ls-remote", "origin", f"refs/heads/{RUN}"], cwd=repo, capture_output=True,
                            text=True, check=True).stdout.split()[0]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=run.worktree, capture_output=True, text=True,
                          check=True).stdout.strip()
    assert pushed == head != first_push             # the fix commits reached the open pull request's branch


def test_red_ci_at_the_loop_maximum_blocks_the_run(parked, prs):
    eng, run_dir, pr = parked
    run = state.read_run(run_dir)
    run.loops = {"verify->implement:ci": 2}  # the verify stage's on_fail max
    lock = state.acquire_lock(run_dir, "test")
    state.write_run(run_dir, run, lock=lock)
    state.release(lock)
    prs.set_ci(pr, "red", "lint: FAILURE")
    eng.tick(RUN)
    run = state.read_run(run_dir)
    assert run.status == "blocked" and run.attention.kind == "blocked"


def test_an_unreachable_github_leaves_the_run_waiting(parked, prs):
    eng, run_dir, pr = parked
    prs.fail_next = FactoryError("git.network", "gh is unreachable")
    eng.tick(RUN)
    assert state.read_run(run_dir).status == "awaiting_approval"


def test_a_stage_waiting_on_a_person_is_not_a_merge_review(new_run, engine):
    run_dir = new_run()
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    eng.run([RUN])
    run = state.read_run(run_dir)
    run.stages[-1].status = "awaiting_approval"
    assert not delivery.at_merge_review(run)


# ---- owner decision D1 (ADR 2026-11-21-auto-merge-is-checked-at-open-and-at-green) ---------------------------------

def test_the_pull_request_body_carries_the_merge_verdict_from_the_moment_it_opens(parked, prs):
    eng, run_dir, pr = parked
    body = prs.prs[pr.number].body
    assert "## Merge\nHuman review:" in body
    assert "Not evaluated" not in body
    assert (run_dir / "merge.json").is_file()


def test_the_person_who_raised_the_request_is_asked_to_review_when_it_opens(parked, prs):
    eng, run_dir, pr = parked
    assert prs.prs[pr.number].reviewers == ["alice"]
    assert "merge" not in prs.calls


def test_a_request_from_the_cli_asks_nobody_and_still_waits_for_review(new_run, engine, prs):
    run_dir = new_run()  # a CLI request: its author is not a GitHub login
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    assert eng.run([RUN]).runs == {RUN: "awaiting_approval"}
    pr = state.read_run(run_dir).pr
    assert prs.prs[pr.number].reviewers == []
    assert state.read_run(run_dir).attention.kind == "merge_review"


def test_green_ci_runs_the_merge_check_again_once_and_records_it(parked, prs):
    eng, run_dir, pr = parked
    prs.set_ci(pr, "green")
    eng.tick(RUN)
    evaluated = [e for e in state.read_events(run_dir) if e.type == "merge_evaluated"]
    assert [e.data.get("ci") for e in evaluated] == ["pending", "green"]
    eng.tick(RUN)  # green again: no third verdict
    assert len([e for e in state.read_events(run_dir) if e.type == "merge_evaluated"]) == 2
    assert state.read_run(run_dir).status == "awaiting_approval"


def test_green_ci_with_every_rule_passing_asks_github_to_merge(parked, prs, monkeypatch):
    eng, run_dir, pr = parked
    real = delivery.evaluate_merge

    def all_pass(run_dir_, cfg, *, changed, ci):
        d = real(run_dir_, cfg, changed=changed, ci=ci)
        return delivery.MergeDecision(auto=(ci == "green"), rules=d.rules, reason="every rule passed")

    monkeypatch.setattr(delivery, "evaluate_merge", all_pass)
    prs.set_ci(pr, "green")
    eng.tick(RUN)
    assert prs.prs[pr.number].auto_merge is True and prs.prs[pr.number].merged_with == "squash"


def test_a_merge_refused_by_branch_protection_leaves_the_run_waiting_for_a_person(parked, prs, monkeypatch):
    eng, run_dir, pr = parked
    monkeypatch.setattr(delivery, "evaluate_merge",
                        lambda *a, ci, **k: delivery.MergeDecision(auto=True, rules=[], reason="every rule passed"))
    prs.set_ci(pr, "green")
    prs.fail_next = None
    real_merge = prs.merge

    def refuse(*a, **k):
        raise FactoryError("git.command_failed", "gh pr merge: base branch policy prohibits the merge")

    prs.merge = refuse
    eng.tick(RUN)
    run = state.read_run(run_dir)
    assert run.status == "awaiting_approval" and run.attention.kind == "merge_review"
    assert any(e.type == "merge_blocked" for e in state.read_events(run_dir))
    prs.merge = real_merge


def test_the_verdict_at_green_is_posted_on_the_pull_request_as_a_comment(parked, prs):
    eng, run_dir, pr = parked
    prs.set_ci(pr, "green")
    eng.tick(RUN)
    comments = prs.prs[pr.number].comments
    assert len(comments) == 1 and comments[0].startswith("Merge check with CI green:")
    assert "Human review:" in comments[0]
    assert "CI is pending" in prs.prs[pr.number].body  # the body keeps the verdict it opened with
