"""Section 20 (last box): the GitHub stub fails for longer than one tick.

The box says the run is `retrying`, recovers when the stub does, and is blocked only after `infra_wait_hours`. The engine
does the middle part today: a run whose pull request cannot be opened is left where it was, and the next pass opens it
once GitHub answers. It does not do the first and last parts: nothing calls `rework.start_infra_wait` or
`rework.infra_tick`, so the run never becomes `retrying` and a sustained outage never blocks it. The last two tests state
that part as strict `xfail`s, so they fail the suite the day the engine is wired, and the box can be ticked then.
"""

import pytest
from engine_helpers import chore_script

from factory_engine import state
from factory_engine.errors import FactoryError

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


_NOT_WIRED = ("the engine never calls rework.start_infra_wait or rework.infra_tick, so a GitHub outage leaves the run "
              "`running` and never blocks it")


@pytest.mark.xfail(strict=True, reason=_NOT_WIRED)
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


@pytest.mark.xfail(strict=True, reason=_NOT_WIRED)
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
