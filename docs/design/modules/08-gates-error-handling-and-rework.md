# 8. Module: gates, error handling and rework

Part of the [phase 1 design](../phase-1.md#module-map). Build wave: 2. Contracts and acceptance criteria are in this file; shared types are in [section 18](../shared/18-shared-contracts.md). Terms such as run, stage, task, attempt and rework are defined in the [glossary](../phase-1.md#2-glossary).

The engine sorts every failure into one class, and each class has a fixed response. A failed gate routes the run back to an earlier stage with a feedback record. When retries or loops run out, the run is blocked and shown under Needs you.

| Class | Examples | Engine response | Limit |
| --- | --- | --- | --- |
| Worker error | Crash, non-zero exit, timeout, no artifact, artifact fails its schema | Retry the same task from its last checkpoint as a new attempt | `retries` per task (default 2) |
| Infrastructure error | Git lock file, network, GitHub rate limit, disk full | Retry the operation with backoff (waits of 5 s and 30 s between three tries). The worker never sees it | 3 tries, then the run waits as `retrying` and each tick tries again until `infra_wait_hours` (default 6) pass, then blocked |
| Gate failure | Tests fail (a `cmd` task exits non-zero), scope violation, blocking review finding | Rework: route to `on_fail.goto` with a feedback record | `on_fail.max` loops per edge |
| No test results | The verify stage's tasks report 0 test cases together: no JUnit file was written, or the files hold no test case | Blocked, with a reason naming the missing files, so no pull request opens. `factory skip <run> --gate no-test-results` passes it (a repo with no tests); a skip turns off auto-merge | None (owner decision T1; ADRs [no test results stops the run](../../adr/2026-11-17-no-test-results-stops-the-run.md) and [T1 skip](../../adr/2026-11-17-t1-skip-is-a-named-block-skip.md)) |
| Merge conflict at join | Two task branches change the same lines | Abort the merge, route to `on_conflict.goto` | `on_conflict.max` |
| Human rework | You answer rework at an approval | Route to `on_reject.goto` with your notes as feedback | None |
| Human reject | You answer reject | Run aborted | None |
| Engine crash | Process killed, machine asleep | On the next start, open attempts become interrupted and resume | Does not use retries; `max_interruptions` per task (a task key, an integer of 0 or more, default 3). A task fails when its `interrupted` attempts reach the value, so with the default the 3rd interruption fails it and two still resume. `0` fails it at the first crash |

**Rework, step by step** (verify fails in a bug-fix run)

1. Task `be-tests` (`make test-api`) exits non-zero. For a `cmd` task that is a check failure, so the stage's `on_fail` applies. The engine logs `gate_failed`.
2. It writes a feedback record into the fix stage's task folders and logs `routed_back` with `verify->fix` loop 1 of 3.
3. Stages from fix onward reset to pending. Earlier stages stay done. The run branch keeps the commits of every stage that already passed, so fix continues from the current code rather than starting over. The one exception is the stage whose own gate failed: the engine resets the run branch to the commit before that stage's join, so a failed stage leaves no commits behind. This reset is built in module 6B and tested there (`test_a_failed_gate_resets_the_run_branch_to_its_pre_join_commit`). Here verify's join added only tests, so fix's commits stay and verify's join is undone. If fix's own gate had failed, fix's join would be undone and fix would start again from the code before it.
4. The fix worker's prompt includes the feedback record. It fixes the failing test, then verify runs again.
5. Verify fails again, and each failure routes back as loop 2, then loop 3 of 3. If verify fails a fourth time, the loop maximum is exceeded. The run becomes blocked, raises an attention item and notifies you.

```json
{
  "schema_version": 1,
  "from_stage": "verify", "to_stage": "fix", "loop": 1, "max": 3,
  "gate": "cmd: [make, test-api]", "exit_code": 1,
  "failed_tests": ["test_refresh_token_expired"],
  "output_tail": "last 200 lines of the gate output",
  "changed_files": ["services/api/auth.py"],
  "at": "2026-11-14T10:20:00+08:00"
}
```

Every field is extracted by code: the gate's exit code and output, JUnit XML for test names, `git diff --name-only` for changed files.

**When a run is blocked**, its decision file offers these options, also available as commands:

- `factory retry <run> [--stage <s>] [--note "..."]` runs the stage again once more, with your note queued on each task of the stage. A failed task starts again with a fresh state. Loop counters do not change, and `run_retried` is logged.
- `factory goto <run> <stage>` routes the run to the blocked stage or any earlier one. That stage and every later stage start again. It takes no loop count, because a person chose the route, and `run_routed` is logged.
- `factory skip <run> --gate <id> --reason "..."` passes a gate marked `skippable: true` on the blocked stage. `<id>` is the gate's name as its results carry it (`cmd: [make, lint]`, `schema: stage-report` or the check name). A reason is required. It logs `gate_skipped` with the reason, marks the stage `skipped`, and the run can no longer be auto-merged. A gate not marked `skippable` is refused. One exception: `--gate no-test-results` passes the T1 block (no test results), which is not a gate in the workflow. It is accepted only when the run is blocked by T1 (`run_blocked` with code `gate.no_test_results`), and refused on any other block (ADR `2026-11-17-t1-skip-is-a-named-block-skip`).
- All three refuse a run that is not `blocked`.
- `factory abort <run>` stops the run, and housekeeping cleans it up.

**On the dashboard**

- The run row turns amber while reworking and red when blocked or failed.
- The stage strip draws the loop back, such as `verify → fix 1/3`.
- The run detail shows a failure panel with the gate, exit code, failing tests, output tail and a link to the feedback record.
- Blocked runs count toward Needs you.

**Module contract: 8 Gates, error handling and rework**

- **Depends on:**
  - 3: `validate`
  - 18: `Stage`, `GateSpec`, `OnFail` (in `types.py`)
  - 6A: `task_dir`, `append_event`
  - check providers resolved by name: 4 (`type-resolved`), 7 (`scope-diff`), 9 (`helpers-ledger`), 11 (`decision-approved`, `packet-hash-matches`)
- **Writes:** feedback records in `tasks/<task>/feedback/`; events `gate_passed`, `gate_failed`, `routed_back`, `run_blocked`.
- **CLI it backs:** none directly; used by 6B.

```python
# gates.py
def run_gates(gates: list[GateSpec], ctx: GateContext) -> list[GateResult]   # in order, stop at first failure
def known_checks() -> set[str]                                               # names only, no imports
def parse_junit(paths: list[Path]) -> TestReport
# checks.py: name -> "module:function", imported lazily when a gate runs
CHECKS = {"scope-diff": "gitops:check_scope_diff", "helpers-ledger": "prompt:check_helpers_ledger",
          "type-resolved": "triage:check_type_resolved", "decision-approved": "decisions:check_approved",
          "packet-hash-matches": "decisions:check_packet_hash", "no-blocking-findings": "gates:check_findings",
          "evidence-cites-code": "gates:check_evidence", "every-claim-has-source": "gates:check_sources",
          "lint-clean": "toolchains:check_lint_clean", "build-matches-stack": "decisions:check_build_stack"}
# rework.py
def classify(failure: FactoryError | AttemptResult | GateResult | JoinResult) -> ErrorKind
def with_backoff(fn: Callable[[], T], *, delays: tuple[int, ...] = (5, 30), clock: Clock) -> T
def build_feedback(run_dir: Path, *, from_stage: str, to_stage: str, result: GateResult | JoinResult,
                   loop: int, max_loops: int, task_ids: list[str]) -> Path
def route(run: Run, wf: Workflow, stage: Stage, failure: ErrorKind | Outcome) -> Routing
    """retry task | goto stage (with stages to reset) | wait (retrying) | blocked | aborted."""
```

Plugins can add checks by placing a function in their `gates/` folder; the name is registered as plugin:\<name>/\<check> when the plugin is enabled, and the function runs in a separate Python process that gets the GateContext as JSON and returns a GateResult.

- **Run and test:** `pytest factory/engine/tests/gates factory/engine/tests/rework` with recorded gate outputs.
- **Errors:** a routing loop is bounded by persisted counters; at the maximum the run is blocked.
- **Decisions taken while building (wave 2).** The backoff has three tries and two waits, 5 s and 30 s, so the default is `(5, 30)`. A third wait of 2 min is not used. A `cmd` task's non-zero exit is a gate failure, so 6B passes its result to `cmd_gate_result`; `classify` alone reads a bare non-zero exit as a worker error. `max` is the number of loops an edge allows: `max: 3` routes the first three failures and blocks the fourth. The shipped `bug-fix.yaml` and the module 5 `bug-fix` example use 3 on `verify->fix`, the value the walkthrough uses (owner decision, wave 3). The other shipped edges keep their values: `fix->root-cause` 2, `fix` conflict 1, `review->fix` 1, and `chore` 2 on both edges. A gate command that is missing is `gate.command_missing`, kind `human`, as module 9 gives a missing binary.

**Gate commands run sandboxed.** A `cmd` gate such as `[make, build]` runs through `CommandAdapter`, so it runs under `srt` with the worker's read and write rules ([module 9](09-worker-adapters-and-governed-helpers.md)). A gate that needs a domain or a cache folder gets them the way a task does. The exit code is the one the command returned: 0 passes, any other value is a gate failure, and a missing binary or a sandbox that cannot start is a task error, not a gate failure.

Acceptance criteria:

- [ ] Each failure type in the class table maps to exactly one handling type. (not ticked: the human rework and reject rows are routed by `route` on a fake Outcome, and no test drives a real module 11 answer through the engine. The engine crash row is tested: `factory/engine/tests/engine/test_max_interruptions.py`, which simulates the engine's death mid-attempt and resumes it, and `test_kill_the_engine_mid_task_then_resume`, which kills a real child engine process and resumes it once)
- [ ] A `cmd` gate runs under `srt`; its exit code decides pass or fail, and a missing binary is a task error. (not ticked: no test runs under `srt`, because the gate tests replace the runner with a stub, so the real `CommandAdapter` (merged in module 9) is not exercised through a gate; the exit-code and missing-binary parts are asserted by `factory/engine/tests/gates/test_gates.py::test_a_cmd_gate_passes_on_exit_0_and_fails_on_any_other_exit` and `::test_a_missing_gate_binary_is_a_task_error_not_a_failed_gate`)
- [x] A verify stage whose tasks report 0 test cases blocks the run with a reason naming the missing JUnit files, and opens no pull request. (test: factory/engine/tests/engine/test_verify_report.py::test_a_verify_stage_with_no_test_cases_blocks_the_run_and_names_the_missing_junit_files; decision T1, 2026-11-17)
- [x] `factory skip <run> --gate no-test-results` passes the T1 block, logs `gate_skipped` and stops auto-merge; on any other block it is refused and the run stays blocked. (test: factory/engine/tests/engine/test_t1_skip.py::test_a_skip_passes_the_zero_test_block_for_a_repo_with_no_tests; ::test_the_t1_skip_is_refused_when_the_run_is_blocked_by_anything_else; ADR 2026-11-17-t1-skip-is-a-named-block-skip)
- [x] Gates stop at the first failure and return the output tail. (test: factory/engine/tests/gates/test_gates.py::test_gates_run_in_order_and_stop_at_the_first_failure; factory/engine/tests/gates/test_gates.py::test_a_failing_gate_returns_the_output_tail_of_the_last_200_lines)
- [x] A feedback record holds the gate, exit code, failing test names and changed files, all taken from command output. (test: factory/engine/tests/gates/test_gates.py::test_feedback_fields_come_from_the_command_output_and_git; factory/engine/tests/rework/test_rework.py::test_a_feedback_record_holds_gate_exit_code_failing_tests_and_changed_files)
- [x] `route` resets the target stage and every later stage, and leaves earlier stages done. (test: factory/engine/tests/rework/test_rework.py::test_route_resets_the_target_stage_and_every_later_stage_and_leaves_earlier_stages_done)
- [x] Loop counters survive an engine restart. (test: factory/engine/tests/rework/test_rework.py::test_loop_counters_survive_an_engine_restart)
- [x] A rate-limit error is retried by `with_backoff` and never counts against task retries. (test: factory/engine/tests/rework/test_rework.py::test_a_rate_limit_is_retried_by_backoff_and_never_counts_against_task_retries)
- [x] Three failed tries put the run in `retrying` with the operation and start time in `run.json`; the next tick tries again and clears the state on success; after `infra_wait_hours` the run is blocked with an attention item. (test: factory/engine/tests/rework/test_rework.py::test_three_failed_tries_put_the_run_in_retrying_with_the_operation_and_start_time; factory/engine/tests/rework/test_rework.py::test_the_next_tick_tries_again_and_clears_the_state_on_success; factory/engine/tests/rework/test_rework.py::test_after_infra_wait_hours_the_run_is_blocked_with_an_attention_item)
- [x] `skip` passes only a gate marked `skippable: true`, requires a reason, logs `gate_skipped` and stops auto-merge; a gate not marked is refused and the run stays blocked. (test: factory/engine/tests/drivers/test_blocked_actions.py::test_skip_passes_a_skippable_gate_logs_the_reason_and_blocks_auto_merge; ::test_skip_refuses_a_gate_the_workflow_did_not_mark_skippable; ::test_skip_needs_a_reason; ::test_no_shipped_gate_is_skippable. Tested through `factory_engine.api`, not yet through the CLI, which module 16 has not built)
- [x] `retry` queues the note on the blocked stage's tasks and returns the run to running without changing loop counters; `goto` sends the run to an earlier stage and resets it; both refuse a run that is not blocked and a stage the workflow lacks. (test: factory/engine/tests/drivers/test_blocked_actions.py::test_retry_queues_the_note_and_moves_the_blocked_run_back_to_running; ::test_retry_refuses_a_run_that_is_not_blocked; ::test_goto_routes_a_blocked_run_to_an_earlier_stage_and_resets_it; ::test_goto_refuses_a_stage_the_workflow_does_not_have. Through `factory_engine.api` only)
- [ ] A repo hook failing on the join commit or push is classified as rework, with the hook output in the feedback record; a hook failing on a network or missing-tool error is classified as transient. (not ticked: a join-commit hook failure reaches feedback only as a fixed sentence, because `JoinResult` carries no hook output; push hooks have no test; the output test uses `hook_failure_result`, not the join path)
