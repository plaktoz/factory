"""Section 20 (last box): the GitHub stub fails for longer than one tick.

The box says the run is `retrying`, recovers when the stub does, and is blocked only after `infra_wait_hours`. Delivery
retries each call three times with backoff (module 8); a call that still fails leaves the run `retrying` with the
operation and the start time in run.json, the next tick repeats the call, and the run is blocked once the wait is older
than `infra_wait_hours`.
"""

from engine_helpers import chore_script

from factory_engine import state
from factory_engine.errors import FactoryError
from factory_engine.types import Request, Source

RUN = "bump-q1w2e"


class GitHubDown:
    """Makes every call of the pull request fake raise a network error until `up` is set."""

    def __init__(self, prs):
        self.up = False
        self._real = {n: getattr(prs, n) for n in ("create", "state", "request_reviewers", "comment", "merge")}
        for name in self._real:
            setattr(prs, name, self._guard(name))

    def _guard(self, name):
        def call(*args, **kwargs):
            if not self.up:
                raise FactoryError("git.network", f"github is down ({name})")
            return self._real[name](*args, **kwargs)
        return call


def fail_calls(prs, name, times):
    """Makes the first `times` calls of one pull request fake method raise a network error; the later calls go through."""
    real, left = getattr(prs, name), [times]

    def call(*args, **kwargs):
        if left[0] > 0:
            left[0] -= 1
            raise FactoryError("git.network", f"github is down ({name})")
        return real(*args, **kwargs)
    setattr(prs, name, call)


def _pass(eng):
    """One engine pass, as a tick's engine does it. An outage may end the pass with the error; the run keeps its state."""
    try:
        return eng.run([RUN]).runs[RUN]
    except FactoryError as e:
        assert e.code == "git.network"
        return None


def test_a_run_whose_pull_request_cannot_be_opened_for_several_passes_finishes_when_github_recovers(new_run, engine, prs):
    run_dir = new_run()
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    github = GitHubDown(prs)
    for _ in range(3):  # three ticks inside the outage
        _pass(eng)
        run = state.read_run(run_dir)
        assert run.pr is None and prs.prs == {}  # nothing was opened, and no half-opened pull request is recorded
        assert run.status not in ("blocked", "failed", "aborted")
    github.up = True
    assert _pass(eng) == "awaiting_approval"
    run = state.read_run(run_dir)
    assert run.pr is not None and len(prs.prs) == 1  # exactly one pull request, opened once GitHub answered
    assert run.status == "awaiting_approval" and run.attention.kind == "merge_review"


def test_an_outage_puts_the_run_in_retrying_and_it_recovers_when_github_does(new_run, engine, prs):
    run_dir = new_run()
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    github = GitHubDown(prs)
    _pass(eng)
    run = state.read_run(run_dir)
    assert run.status == "retrying" and run.infra_wait is not None  # the outage is waited out, not raised
    assert "github is down" in run.infra_wait.last_error
    _pass(eng)
    assert state.read_run(run_dir).status == "retrying"
    github.up = True
    assert _pass(eng) == "awaiting_approval"  # recovers when the stub does, and the wait is cleared
    assert state.read_run(run_dir).infra_wait is None


def test_an_outage_blocks_the_run_only_after_infra_wait_hours(new_run, engine, prs, clock):
    run_dir = new_run()
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    GitHubDown(prs)
    _pass(eng)
    clock.advance(5 * 3600 + 59 * 60)  # inside the six hours: still waiting
    _pass(eng)
    assert state.read_run(run_dir).status == "retrying"
    clock.advance(120)  # past the six hours
    _pass(eng)
    run = state.read_run(run_dir)
    assert run.status == "blocked" and run.attention is not None and run.attention.kind == "blocked"


def test_three_failed_tries_leave_the_run_waiting_and_the_next_pass_opens_the_pull_request_once(new_run, engine, prs, clock):
    run_dir = new_run()
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    fail_calls(prs, "create", times=3)
    assert _pass(eng) == "retrying"  # the three tries of the first pass fail: waits of 5 s and 30 s, then the run waits
    run = state.read_run(run_dir)
    assert run.pr is None and prs.prs == {} and clock.sleeps[-2:] == [5, 30]
    assert run.infra_wait.tries == 3 and "github is down" in run.infra_wait.last_error
    assert _pass(eng) == "awaiting_approval"  # the next pass's first try goes through
    run = state.read_run(run_dir)
    assert run.infra_wait is None and run.pr is not None and len(prs.prs) == 1
    types = [e.type for e in state.read_events(run_dir)]
    assert types.count("infra_waiting") == 1 and types.count("infra_recovered") == 1


def test_a_reviewer_request_that_fails_leaves_the_recorded_pull_request_alone_and_asks_on_the_next_pass(new_run, engine, prs):
    """A request from a GitHub issue by alice, opened by another account, so alice is asked to review."""
    src = Source("github", "acme/report#1", "Bump the lint config", "Bump it.", ["chore"], "alice", [])
    run_dir = new_run(request=Request("gh-1", src, "sha1", "repo", "Bump the lint config", "chore", "explicit", None, []))
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    prs.login = "factory"
    fail_calls(prs, "request_reviewers", times=3)
    assert _pass(eng) == "retrying"
    run = state.read_run(run_dir)
    assert run.pr is not None and len(prs.prs) == 1  # recorded before its reviewers are asked, so no second one
    assert _pass(eng) == "awaiting_approval"
    assert len(prs.prs) == 1 and prs.calls.count("create") == 1
    assert prs.prs[run.pr.number].reviewers == ["alice"] and state.read_run(run_dir).infra_wait is None


def test_a_person_retries_a_run_blocked_by_an_outage_and_the_next_outage_starts_a_fresh_wait(new_run, engine, prs, clock):
    run_dir = new_run()
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    github = GitHubDown(prs)
    _pass(eng)
    clock.advance(6 * 3600)
    _pass(eng)
    assert state.read_run(run_dir).status == "blocked"
    eng.retry(RUN)  # a person's retry is a new attempt: the old wait does not carry over
    assert state.read_run(run_dir).infra_wait is None
    assert _pass(eng) == "retrying"  # still down: a fresh wait starts, so the run is not blocked again at once
    run = state.read_run(run_dir)
    assert run.status == "retrying" and run.infra_wait.tries == 3
    github.up = True
    assert _pass(eng) == "awaiting_approval"
