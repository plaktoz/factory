"""Module 8 rework acceptance: one handling type per failure, backoff, feedback records, routing, loop counters, waits."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from factory_engine import rework, state
from factory_engine.adapters.worker.fake import failed, ok, timeout
from factory_engine.atomic import read_jsonl
from factory_engine.clock import FakeClock
from factory_engine.errors import CATALOGUE, FactoryError
from factory_engine.lock import acquire_lock, release
from factory_engine.rework import (build_feedback, classify, infra_recovered, infra_tick, may_retry, route,
                                   route_conflict, start_infra_wait, with_backoff)
from factory_engine.types import (Defaults, GateResult, GateSpec, JoinResult, OnFail, Policy, Request, Source, Stage,
                                  StageState, Workflow)
from factory_engine.validate import validate


def stage(sid: str, *, on_fail: OnFail | None = None, on_conflict: OnFail | None = None,
          on_reject: str | None = None) -> Stage:
    return Stage(id=sid, needs=[], tasks=[], tasks_from=None, join="all", gate=[], on_fail=on_fail,
                 on_conflict=on_conflict, approval="none", on_reject=on_reject, sync_base=False, source="workflow")


def bug_fix() -> Workflow:
    stages = [stage("reproduce"), stage("root-cause"), stage("propose", on_reject="root-cause"),
              stage("fix", on_conflict=OnFail("fix", 3)), stage("verify", on_fail=OnFail("fix", 3)),
              stage("review", on_fail=OnFail("fix", 1))]
    return Workflow(name="bug-fix", type="bug", sink="pull_request", policy=Policy(True, []),
                    defaults=Defaults(2, 30, 10, 3), stages=stages, regenerate_at_join=[], join_cmd=None,
                    shared_files={})


def make_run(tmp_path: Path, status_by_stage: dict[str, str] | None = None):
    rq = Request("gh-1", Source("cli", "x", "t", "b", [], None, []), "sha", "repo", "t", "bug", None, None, [])
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    ref = state.init_run(tmp_path / "home", repo, "local/repo", "run-1", rq, branch="run-1",
                         worktree=tmp_path / "wt", kit_hash="x")
    run = state.read_run(ref.run_dir)
    wf = bug_fix()
    done = status_by_stage or {s.id: "done" for s in wf.stages}
    run.workflow, run.status, run.stage = "bug-fix", "running", "verify"
    run.stages = [StageState(s.id, 1, done.get(s.id, "pending"), ["t"], "2026-11-14T10:00:00+08:00",
                             "2026-11-14T10:05:00+08:00") for s in wf.stages]
    return ref.run_dir, run, wf


def by_id(wf: Workflow, sid: str) -> Stage:
    return next(s for s in wf.stages if s.id == sid)


def gate_result(code="gate.exit_code", output_tail="", passed=False) -> GateResult:
    return GateResult(passed=passed, gate="cmd: [make, test-api]", code=code, output_tail=output_tail,
                      details={"exit_code": 1, "failed_tests": ["test_refresh_token_expired"],
                               "changed_files": ["services/api/auth.py"]})


# --- the class table: each failure type maps to exactly one handling type -------------------------------------

@pytest.mark.parametrize("failure,expected", [
    (failed("crash"), "task_retry"),                                  # worker crash
    (failed("crash", exit_code=137), "task_retry"),                   # non-zero exit
    (timeout(), "task_retry"),                                        # timeout
    (ok(artifact=None), "task_retry"),                                # no artifact
    (failed("rate_limit"), "transient"),                              # rate limit
    (failed("auth"), "human"),
    (failed("binary_missing"), "human"),
    (failed("model_not_found"), "human"),
    (gate_result(code="gate.schema"), "task_retry"),                  # artifact fails its schema
    (gate_result(code="gate.no_artifact"), "task_retry"),
    (gate_result(code="gate.exit_code"), "rework"),                   # tests fail
    (gate_result(code="gate.scope_violation"), "rework"),             # scope violation
    (gate_result(code="gate.findings"), "rework"),                    # blocking review finding
    (JoinResult(False, ["a.py"], False, []), "rework"),               # merge conflict (routed by route_conflict)
    (JoinResult(False, [], True, []), "rework"),                      # repo hook failed on the join commit
    (FactoryError("git.network", "rate limited"), "transient"),       # infrastructure
    (FactoryError("git.index_locked", "lock file"), "transient"),
    (FactoryError("git.push_rejected", "rejected"), "human"),
    (FactoryError("config.invalid", "bad"), "fail_fast"),
    (FactoryError("git.command_failed", "boom"), "task_retry"),
])
def test_each_failure_type_maps_to_exactly_one_handling_type(failure, expected):
    assert classify(failure) == expected


def test_something_that_did_not_fail_is_not_classified():
    with pytest.raises(ValueError):
        classify(gate_result(passed=True))
    with pytest.raises(ValueError):
        classify(JoinResult(True, [], False, ["abc"]))


def test_a_repo_hook_failing_on_a_real_defect_is_rework_and_a_network_or_missing_tool_is_transient():
    lint = FactoryError("git.hook_failed", "pre-commit: ruff found 3 errors in services/api/auth.py")
    assert classify(lint) == "rework"
    for text in ("pre-commit: Could not resolve host: pypi.org", "pre-commit: ruff: command not found",
                 "husky: Connection timed out"):
        assert classify(FactoryError("git.hook_failed", text)) == "transient", text
    assert classify(rework.hook_failure_result(lint)) == "rework"
    offline = FactoryError("git.hook_failed", "pre-push: Network is unreachable")
    assert classify(rework.hook_failure_result(offline)) == "transient"


def test_a_hook_failure_carries_its_output_into_the_feedback_record(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    hook = rework.hook_failure_result(FactoryError("git.hook_failed", "pre-commit: ruff found 3 errors"))
    path = build_feedback(run_dir, from_stage="fix", to_stage="fix", result=hook, loop=1, max_loops=2,
                          task_ids=["backend"])
    doc = json.loads(path.read_text())
    assert doc["gate"] == "repo hook" and "ruff found 3 errors" in doc["output_tail"]


def test_the_error_kind_a_module_raises_is_what_classify_returns():
    for code, entry in CATALOGUE.items():
        if code == "git.hook_failed":
            continue
        assert classify(FactoryError(code, "x")) == entry.kind


def test_the_retry_limit_per_task_defaults_to_two_retries():
    assert [may_retry(n, 2) for n in (1, 2, 3)] == [True, True, False]


# --- with_backoff ---------------------------------------------------------------------------------------------

def test_a_transient_error_is_retried_after_5_and_30_seconds():
    clock = FakeClock()
    calls = []

    def flaky():
        calls.append(len(calls))
        if len(calls) < 3:
            raise FactoryError("git.network", "rate limited")
        return "done"

    assert with_backoff(flaky, clock=clock) == "done"
    assert (len(calls), clock.sleeps) == (3, [5, 30])


def test_success_on_the_first_try_never_sleeps():
    clock = FakeClock()
    assert with_backoff(lambda: 7, clock=clock) == 7
    assert clock.sleeps == []


def test_when_every_try_fails_the_last_error_is_raised_for_the_caller_to_classify():
    clock = FakeClock()
    tries = []

    def down():
        tries.append(1)
        raise FactoryError("git.network", "down")

    with pytest.raises(FactoryError) as err:
        with_backoff(down, clock=clock)
    assert err.value.code == "git.network"
    assert (len(tries), clock.sleeps) == (3, [5, 30])


def test_an_error_that_is_not_transient_is_raised_at_once_without_a_retry():
    clock = FakeClock()
    calls = []

    def bad():
        calls.append(1)
        raise FactoryError("git.auth_expired", "login expired")

    with pytest.raises(FactoryError):
        with_backoff(bad, clock=clock)
    assert (len(calls), clock.sleeps) == (1, [])


def test_a_rate_limit_is_retried_by_backoff_and_never_counts_against_task_retries():
    clock = FakeClock()
    results = iter([failed("rate_limit"), failed("rate_limit"), ok(artifact=Path("a.json"))])
    attempts = []

    def worker_attempt():
        attempts.append(1)
        return next(results)

    final = with_backoff(worker_attempt, clock=clock)
    assert final.exit == "ok" and len(attempts) == 3 and clock.sleeps == [5, 30]
    assert classify(failed("rate_limit")) == "transient"


def test_rate_limits_that_never_clear_come_back_as_the_last_result_to_classify():
    clock = FakeClock()
    final = with_backoff(lambda: failed("rate_limit"), clock=clock)
    assert final.error_kind == "rate_limit" and clock.sleeps == [5, 30]
    assert classify(final) == "transient"


# --- feedback records -----------------------------------------------------------------------------------------

def test_a_feedback_record_holds_gate_exit_code_failing_tests_and_changed_files(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    result = gate_result(output_tail="E assert 401 == 200\nFAILED test_refresh_token_expired")
    path = build_feedback(run_dir, from_stage="verify", to_stage="fix", result=result, loop=1, max_loops=2,
                          task_ids=["backend", "frontend"])
    doc = json.loads(path.read_text())
    validate(doc, "feedback")
    assert (doc["from_stage"], doc["to_stage"], doc["loop"], doc["max"]) == ("verify", "fix", 1, 2)
    assert doc["gate"] == "cmd: [make, test-api]" and doc["exit_code"] == 1
    assert doc["failed_tests"] == ["test_refresh_token_expired"]
    assert doc["changed_files"] == ["services/api/auth.py"]
    assert doc["output_tail"].endswith("FAILED test_refresh_token_expired")
    for task in ("backend", "frontend"):
        assert (run_dir / "tasks" / task / "feedback").glob("*.json")
        assert len(list((run_dir / "tasks" / task / "feedback").glob("*.json"))) == 1


def test_feedback_for_a_merge_conflict_lists_the_conflicting_files(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    join = JoinResult(False, ["services/api/auth.py", "web/app.js"], False, [])
    path = build_feedback(run_dir, from_stage="fix", to_stage="fix", result=join, loop=1, max_loops=2,
                          task_ids=["backend"])
    doc = json.loads(path.read_text())
    assert doc["gate"] == "join" and doc["exit_code"] is None
    assert doc["changed_files"] == ["services/api/auth.py", "web/app.js"]
    assert "services/api/auth.py" in doc["output_tail"]


def test_each_new_feedback_record_is_kept_so_the_worker_sees_the_history_newest_last(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    for loop in (1, 2):
        build_feedback(run_dir, from_stage="verify", to_stage="fix", result=gate_result(), loop=loop, max_loops=3,
                       task_ids=["backend"])
    files = sorted((run_dir / "tasks" / "backend" / "feedback").glob("*.json"))
    assert [json.loads(f.read_text())["loop"] for f in files] == [1, 2]


def test_build_feedback_logs_routed_back_with_the_loop(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    build_feedback(run_dir, from_stage="verify", to_stage="fix", result=gate_result(), loop=1, max_loops=2,
                   task_ids=["backend"])
    (event,) = [e for e in read_jsonl(run_dir / "events.jsonl") if e["type"] == "routed_back"]
    assert (event["data"]["from_stage"], event["data"]["to_stage"], event["data"]["loop"],
            event["data"]["max"]) == ("verify", "fix", 1, 2)


# --- route ----------------------------------------------------------------------------------------------------

def test_route_resets_the_target_stage_and_every_later_stage_and_leaves_earlier_stages_done(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    routing = route(run, wf, by_id(wf, "verify"), "rework")
    assert (routing.action, routing.goto, routing.loop, routing.max) == ("goto", "fix", 1, 3)
    assert routing.reset == ["fix", "verify", "review"]
    status = {s.id: s.status for s in run.stages}
    assert status == {"reproduce": "done", "root-cause": "done", "propose": "done",
                      "fix": "pending", "verify": "pending", "review": "pending"}
    assert (run.stage, run.status) == ("fix", "running")
    assert {s.id: s.visit for s in run.stages}["fix"] == 2 and {s.id: s.visit for s in run.stages}["propose"] == 1


def test_the_run_is_blocked_with_an_attention_item_when_the_loop_maximum_is_reached(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    verify = by_id(wf, "verify")
    for loop in (1, 2, 3):                                              # verify -> fix loops 1 to 3 of 3
        run.stage = "verify"
        assert route(run, wf, verify, "rework").action == "goto"
    run.stage = "verify"
    blocked = route(run, wf, verify, "rework")                          # the fourth failure exceeds the maximum
    assert blocked.action == "blocked"
    assert run.status == "blocked"
    assert run.attention is not None and run.attention.kind == "blocked"
    assert run.attention.stage == "verify" and "verify->fix" in run.attention.summary
    assert run.loops == {"verify->fix": 3}                              # no extra loop was taken
    assert run.stage == "verify"                                        # stays where it failed


def test_a_stage_with_a_loop_maximum_of_one_routes_once_then_blocks(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    review = by_id(wf, "review")
    assert route(run, wf, review, "rework").action == "goto"           # loop 1 of 1
    run.stage = "review"
    assert route(run, wf, review, "rework").action == "blocked"        # the second failure exceeds the maximum


def test_a_failed_stage_without_an_on_fail_edge_is_blocked(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    routing = route(run, wf, by_id(wf, "propose"), "rework")
    assert routing.action == "blocked" and run.status == "blocked"


def test_loop_counters_survive_an_engine_restart(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    route(run, wf, by_id(wf, "verify"), "rework")
    lock = acquire_lock(run_dir, "engine-1")
    state.write_run(run_dir, run, lock=lock)
    release(lock)

    restarted = state.read_run(run_dir)                                # a new engine process reads run.json
    assert restarted.loops == {"verify->fix": 1}
    restarted.stage = "verify"
    routing = route(restarted, wf, by_id(wf, "verify"), "rework")
    assert (routing.action, routing.loop) == ("goto", 2)               # the count continues, it does not restart


def test_loop_counters_survive_a_rebuild_from_the_last_snapshot(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    route(run, wf, by_id(wf, "verify"), "rework")
    lock = acquire_lock(run_dir, "engine-1")
    state.write_run(run_dir, run, lock=lock)
    release(lock)
    (run_dir / "run.json").unlink()
    assert state.read_run(run_dir).loops == {"verify->fix": 1}


def test_a_merge_conflict_follows_on_conflict_and_has_its_own_counter(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    fix = by_id(wf, "fix")
    run.stage = "fix"
    first = route_conflict(run, wf, fix)
    assert (first.action, first.goto, first.loop, first.max) == ("goto", "fix", 1, 3)
    assert run.loops == {"fix->fix:conflict": 1}
    for _ in (2, 3):
        run.stage = "fix"
        assert route_conflict(run, wf, fix).action == "goto"
    run.stage = "fix"
    assert route_conflict(run, wf, fix).action == "blocked"


def test_a_merge_conflict_without_on_conflict_is_blocked(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    assert route_conflict(run, wf, by_id(wf, "verify")).action == "blocked"


def test_a_worker_error_is_a_task_retry_and_resets_no_stage(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    before = [(s.id, s.status) for s in run.stages]
    assert route(run, wf, by_id(wf, "fix"), "task_retry").action == "retry_task"
    assert [(s.id, s.status) for s in run.stages] == before


class FakeOutcome:
    """Stands in for module 11's Outcome until it is merged: route reads only .status."""

    def __init__(self, status):
        self.status, self.choices, self.questions, self.notes, self.code, self.message = status, {}, {}, "", None, None


def test_a_human_rework_answer_routes_to_on_reject_again_and_again(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    propose = by_id(wf, "propose")
    for n in range(1, 6):
        run.stage = "propose"
        routing = route(run, wf, propose, FakeOutcome("rework"))
        assert (routing.action, routing.goto, routing.loop) == ("goto", "root-cause", n)
    assert run.status == "running"


def test_a_human_reject_answer_aborts_the_run(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    routing = route(run, wf, by_id(wf, "propose"), FakeOutcome("reject"))
    assert routing.action == "aborted" and run.status == "aborted"


def test_a_human_question_goes_back_to_the_same_stage(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    routing = route(run, wf, by_id(wf, "propose"), FakeOutcome("question"))
    assert (routing.action, routing.goto) == ("goto", "propose")
    assert routing.reset == ["propose", "fix", "verify", "review"]


def test_a_stage_that_routes_forward_or_to_an_unknown_stage_is_refused(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    wf.stages[1] = stage("root-cause", on_fail=OnFail("review", 2))
    with pytest.raises(FactoryError, match="routes forward"):
        route(run, wf, by_id(wf, "root-cause"), "rework")
    wf.stages[1] = stage("root-cause", on_fail=OnFail("nowhere", 2))
    with pytest.raises(FactoryError, match="not a stage"):
        route(run, wf, by_id(wf, "root-cause"), "rework")


def test_a_fail_fast_error_is_never_routed(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    with pytest.raises(ValueError, match="fail_fast"):
        route(run, wf, by_id(wf, "fix"), "fail_fast")


def test_a_human_error_blocks_the_run_with_an_attention_item(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    routing = route(run, wf, by_id(wf, "fix"), "human")
    assert routing.action == "blocked" and run.attention is not None and run.attention.kind == "blocked"
    rework.record_blocked(run_dir, run, routing)
    assert [e["type"] for e in read_jsonl(run_dir / "events.jsonl") if e["type"] == "run_blocked"] == ["run_blocked"]


# --- infrastructure waits -------------------------------------------------------------------------------------

def test_three_failed_tries_put_the_run_in_retrying_with_the_operation_and_start_time(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    clock = FakeClock()
    err = FactoryError("git.network", "github rate limit")

    def rate_limited():
        raise err

    with pytest.raises(FactoryError):
        with_backoff(rate_limited, clock=clock)
    start_infra_wait(run, operation="push run branch", error=err, clock=clock)
    assert run.status == "retrying"
    assert run.infra_wait is not None
    assert run.infra_wait.last_error == "push run branch: github rate limit"
    assert run.infra_wait.since == clock.now().isoformat(timespec="seconds")
    lock = acquire_lock(run_dir, "engine-1")
    state.write_run(run_dir, run, lock=lock)                           # run.json accepts the state (schema-checked)
    release(lock)
    assert state.read_run(run_dir).infra_wait.last_error.startswith("push run branch")


def test_the_next_tick_tries_again_and_clears_the_state_on_success(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    clock = FakeClock()
    err = FactoryError("git.network", "down")
    start_infra_wait(run, operation="push", error=err, clock=clock)
    clock.advance(600)
    assert infra_tick(run, operation="push", error=err, clock=clock, wait_hours=6).action == "wait"
    assert run.status == "retrying" and run.infra_wait.tries == 4
    infra_recovered(run)
    assert run.infra_wait is None and run.status == "running"


def test_after_infra_wait_hours_the_run_is_blocked_with_an_attention_item(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    clock = FakeClock()
    err = FactoryError("git.network", "still down")
    start_infra_wait(run, operation="open pull request", error=err, clock=clock)
    clock.advance(timedelta(hours=5, minutes=59).total_seconds())
    assert infra_tick(run, operation="open pull request", error=err, clock=clock, wait_hours=6).action == "wait"
    clock.advance(120)
    routing = infra_tick(run, operation="open pull request", error=err, clock=clock, wait_hours=6)
    assert routing.action == "blocked" and run.status == "blocked"
    assert run.attention is not None and run.attention.kind == "blocked"
    assert "open pull request" in run.attention.summary


def test_infra_tick_needs_a_run_that_is_waiting(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    with pytest.raises(ValueError):
        infra_tick(run, operation="x", error=FactoryError("git.network", "x"), clock=FakeClock(), wait_hours=6)


def test_infra_recovered_on_a_run_that_was_not_waiting_changes_nothing(tmp_path):
    run_dir, run, wf = make_run(tmp_path)
    run.status = "blocked"
    infra_recovered(run)
    assert run.status == "blocked"


def test_the_shipped_workflows_max_values_are_loops_allowed_so_max_2_routes_twice_then_blocks(tmp_path):
    """Checks the files in factory/workflows against the decided rule (max = loops allowed): bug-fix verify->fix is 2,
    so the first and second failure route back and the third blocks. The values 1 and 2 are valid; none needs a change."""
    from factory_engine.config import Config
    from factory_engine.workflow import load_workflow
    cfg = Config(machine={}, repo={})
    shipped = {"bug-fix": load_workflow(tmp_path, cfg, "bug-fix"), "chore": load_workflow(tmp_path, cfg, "chore")}
    edges = {(n, s.id, e): getattr(s, e).max for n, wf in shipped.items() for s in wf.stages
             for e in ("on_fail", "on_conflict") if getattr(s, e)}
    assert edges == {("bug-fix", "fix", "on_fail"): 2, ("bug-fix", "fix", "on_conflict"): 1,
                     ("bug-fix", "verify", "on_fail"): 2, ("bug-fix", "review", "on_fail"): 1,
                     ("chore", "implement", "on_fail"): 2, ("chore", "verify", "on_fail"): 2}
    run_dir, run, _ = make_run(tmp_path)
    wf = shipped["bug-fix"]
    verify = by_id(wf, "verify")
    run.workflow = "bug-fix"
    outcomes = []
    for _ in range(3):
        run.stage = "verify"
        outcomes.append(route(run, wf, verify, "rework").action)
    assert outcomes == ["goto", "goto", "blocked"]
