# 8. Module: gates, error handling and rework

Part of the [phase 1 design](../phase-1.md#module-map). Build wave: 2. Contracts and acceptance criteria are in this file; shared types are in [section 18](../shared/18-shared-contracts.md). Terms such as run, stage, task, attempt and rework are defined in the [glossary](../phase-1.md#2-glossary).

The engine sorts every failure into one class, and each class has a fixed response. A failed gate routes the run back to an earlier stage with a feedback record. When retries or loops run out, the run is blocked and shown under Needs you.

| Class | Examples | Engine response | Limit |
| --- | --- | --- | --- |
| Worker error | Crash, non-zero exit, timeout, no artifact, artifact fails its schema | Retry the same task from its last checkpoint as a new attempt | `retries` per task (default 2) |
| Infrastructure error | Git lock file, network, GitHub rate limit, disk full | Retry the operation with backoff (waits of 5 s and 30 s between three tries). The worker never sees it | 3 tries, then the run waits as `retrying` and each tick tries again until `infra_wait_hours` (default 6) pass, then blocked |
| Gate failure | Tests fail (a `cmd` task exits non-zero), scope violation, blocking review finding | Rework: route to `on_fail.goto` with a feedback record | `on_fail.max` loops per edge |
| Repo hook failure | A repo hook exits non-zero on the join commit, or stops the push (module 7) | Its output is read as the hook's: a network or missing-tool message (the transient patterns in `rework.py`) waits as `retrying`; any other output is rework, routed through the stage's `on_fail` with the output in the feedback record | As the gate row for rework; as the infrastructure row for transient |
| No test results | The verify stage's tasks report 0 test cases together: no JUnit file was written, or the files hold no test case | Blocked, with a reason naming the missing files, so no pull request opens. `factory skip <run> --gate no-test-results` passes it (a repo with no tests); a skip turns off auto-merge | None (owner decision T1; see Decisions) |
| Merge conflict at join | Two task branches change the same lines | Abort the merge, route to `on_conflict.goto` | `on_conflict.max` |
| Human rework | You answer rework at an approval | Route to `on_reject.goto` and write your notes into each task folder of that stage as a feedback record (`gate: "human"`, `exit_code: null`, empty lists, `notes`); logs `routed_back` | `on_reject` has no limit; the record shows the loop number. A stage with no `on_reject` blocks the run and writes nothing |
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

A human rework writes the same record. The fields a gate does not have hold the values the schema allows for none, and the operator's answer is in `notes`, an optional field that only a human rework sets. Empty notes still write the record, with `notes` as an empty string, so the worker sees that a person sent the stage back. A `reject` writes no record. Example of a human rework:

```json
{
  "schema_version": 1,
  "from_stage": "propose", "to_stage": "root-cause", "loop": 1, "max": 1,
  "gate": "human", "exit_code": null,
  "failed_tests": [], "output_tail": "", "changed_files": [],
  "at": "2026-11-24T10:20:00+08:00",
  "notes": "Keep the old token format; only the expiry check is wrong."
}
```

**When a run is blocked**, its decision file offers these options (a real block writes that file at the stage and visit its `run_blocked` event names, except a triage block with no workflow to retry; `factory/engine/tests/engine/test_blocked_run_writes_a_decision_file.py`), also available as commands:

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
def build_human_feedback(run_dir: Path, *, from_stage: str, to_stage: str, notes: str, loop: int, max_loops: int,
                         task_ids: list[str]) -> Path   # a human rework: gate "human", the notes in `notes`
def route(run: Run, wf: Workflow, stage: Stage, failure: ErrorKind | Outcome) -> Routing
    """retry task | goto stage (with stages to reset) | wait (retrying) | blocked | aborted."""
```

`TestReport` is `total` (the number of test cases the JUnit files hold, so 0 means no results) and `failed` (the names of the failing tests, empty when none). `Routing` is `action` (`retry_task`, `goto`, `wait`, `blocked` or `aborted`), `goto`, `reset` (the stages sent back to pending, in workflow order), `loop`, `max` (0 when the edge has no limit), `reason`, `code` (the error code of a block the engine raised itself, or none) and `key` (the `run.loops` key an edge route counts on, or none). A saved route (`pending-route.json`) holds these fields for a `goto`.

Plugins can add checks by placing a function in their `gates/` folder; the name is registered as plugin:\<name>/\<check> when the plugin is enabled, and the function runs in a separate Python process that gets the GateContext as JSON and returns a GateResult.

- **Run and test:** `pytest factory/engine/tests/gates factory/engine/tests/rework` with recorded gate outputs.
- **Errors:** a routing loop is bounded by persisted counters; at the maximum the run is blocked. A feedback write that fails with an `OSError` part-way (a disk error after the first task folder, for example) is an infrastructure error, as the table's "disk full" row says: the write is tried three times with the backoff, then the run waits as `retrying` with the operation named (`feedback write`, or `feedback write (red CI)` for a red-CI rework) and no routing is applied, so no loop count moves. Before it waits, the route is saved to `pending-route.json` in the run folder (the from-stage, `goto`, `reset`, the loop key, `loop`, `max`, the reason, the code, the task folders and the feedback record), written atomically under the run lock. The next pass that repeats the wait writes the saved record, applies the saved route as `_apply` does, deletes the file, and does not run the check again, so the loop count moves once. Only a wait on a feedback write applies a saved route; a pass that finds a retrying run waiting on anything else (delivery, reviewers) deletes the file, so a route left by a crash is never applied to another operation. `_write_records` skips each task folder that already holds the route's record, so each folder ends with one record. After `infra_wait_hours` the run is blocked and the file is removed, so a person's `factory retry` runs the check again and works the route out from what it finds. `Engine._route_back` covers the five rework call sites (gate, join conflict, human rework, pre-push hook, red CI). A human rework saves no file, because its answer is in the decision file. A schema failure is not an `OSError` and still raises; a malformed `pending-route.json` raises `config.invalid` and is left in place. A save that itself fails with an `OSError` is not fatal: the next pass works the route out again, as it did before the file existed. Built for delivery (module 13): the call that reads who opens the pull request, the sink call and the reviewer request each go through `with_backoff`; three failed tries leave the run `retrying`, and each later engine pass repeats the call. The pull request is recorded in `run.json` before its reviewers are asked, so a failed request never opens a second pull request. A person's `retry` of a blocked run clears the old wait, and a wait left by an earlier outage is cleared when a pass gets through. A tracker call in a comment sink goes through the same `with_backoff`, but has no test of its own.
- **Decisions taken while building (wave 2).** The backoff has three tries and two waits, 5 s and 30 s, so the default is `(5, 30)`. A third wait of 2 min is not used. A `cmd` task's non-zero exit is a gate failure, so 6B passes its result to `cmd_gate_result`; `classify` alone reads a bare non-zero exit as a worker error. `max` is the number of loops an edge allows: `max: 3` routes the first three failures and blocks the fourth. The shipped `bug-fix.yaml` and the module 5 `bug-fix` example use 3 on `verify->fix`, the value the walkthrough uses (owner decision, wave 3). The other shipped edges keep their values: `fix->root-cause` 2, `fix` conflict 1, `review->fix` 1, and `chore` 2 on both edges. A gate command that is missing is `gate.command_missing`, kind `human`, as module 9 gives a missing binary. A repo hook's missing tool is transient, unlike a gate's: the tool belongs to the repo's own environment and is often installed on the next try, so the engine waits for it instead of asking a person (item 50 brief, 2026-11-25; not an owner decision, and not in a `Decisions` row). The engine tells the two apart only by the message text, as `rework.py` `_HOOK_TRANSIENT` lists.

**A silent `cmd` task is reported, not killed.** Not built yet. The planned rule: the engine notes when a running `cmd` task's `worker.log` last grew. After `stall_minutes` with no growth (a task field, default 10, `0` turns the check off), it logs one `task_silent` event and shows it on the task card. It does not kill the task or change its state. Claude tasks are left out. The fields and event are not in the schemas or the event list yet.

**Gate commands run sandboxed.** A `cmd` gate such as `[make, build]` runs through `CommandAdapter`, so it runs under `srt` with the worker's read and write rules ([module 9](09-worker-adapters-and-governed-helpers.md)). A gate that needs a domain or a cache folder gets them the way a task does. The exit code is the one the command returned: 0 passes, any other value is a gate failure, and a missing binary or a sandbox that cannot start is a task error, not a gate failure.

Acceptance criteria:

- [x] Each failure type in the class table maps to exactly one handling type. (test: factory/engine/tests/engine/test_human_rework_and_reject.py::test_a_rework_answers_notes_reach_the_next_prompt_of_the_stage_it_goes_back_to, ::test_a_reject_answer_writes_no_feedback_record; factory/engine/tests/rework/test_rework.py::test_a_human_rework_writes_the_notes_as_a_feedback_record_in_each_target_task_folder, ::test_a_merge_conflict_follows_on_conflict_and_has_its_own_counter, ::test_the_error_kind_a_module_raises_is_what_classify_returns; factory/engine/tests/engine/test_verify_report.py::test_a_verify_stage_with_no_test_cases_blocks_the_run_and_names_the_missing_junit_files; factory/engine/tests/engine/test_max_interruptions.py; factory/engine/tests/engine/test_engine.py::test_kill_the_engine_mid_task_then_resume)
- [x] A `cmd` gate runs under `srt`; its exit code decides pass or fail, and a missing binary is a task error. (test: factory/engine/tests/gates/test_gate_runner_real.py::test_a_cmd_gate_runs_a_real_command_through_command_adapter_when_no_runner_is_installed, ::test_a_real_command_that_exits_non_zero_fails_the_gate_and_returns_its_output, ::test_a_real_gate_command_that_is_not_installed_is_a_task_error_not_a_failed_gate, ::test_a_real_gate_command_cannot_read_the_factory_home; these install no stub, so the real `CommandAdapter` runs; they skip when `srt` or Node 22.12 is missing, and ran on this machine with both present. The stubbed exit-code and missing-binary cases are also in `factory/engine/tests/gates/test_gates.py::test_a_cmd_gate_passes_on_exit_0_and_fails_on_any_other_exit`, `::test_a_missing_gate_binary_is_a_task_error_not_a_failed_gate`)
- [x] A verify stage whose tasks report 0 test cases blocks the run with a reason naming the missing JUnit files, and opens no pull request. (test: factory/engine/tests/engine/test_verify_report.py::test_a_verify_stage_with_no_test_cases_blocks_the_run_and_names_the_missing_junit_files; decision T1, 2026-11-17)
- [x] `factory skip <run> --gate no-test-results` passes the T1 block, logs `gate_skipped` and stops auto-merge; on any other block it is refused and the run stays blocked. (test: factory/engine/tests/engine/test_t1_skip.py::test_a_skip_passes_the_zero_test_block_for_a_repo_with_no_tests; ::test_the_t1_skip_is_refused_when_the_run_is_blocked_by_anything_else; ADR 2026-11-17-t1-skip-is-a-named-block-skip)
- [x] Gates stop at the first failure and return the output tail. (test: factory/engine/tests/gates/test_gates.py::test_gates_run_in_order_and_stop_at_the_first_failure; factory/engine/tests/gates/test_gates.py::test_a_failing_gate_returns_the_output_tail_of_the_last_200_lines)
- [x] A feedback record holds the gate, exit code, failing test names and changed files, all taken from command output. (test: factory/engine/tests/gates/test_gates.py::test_feedback_fields_come_from_the_command_output_and_git; factory/engine/tests/rework/test_rework.py::test_a_feedback_record_holds_gate_exit_code_failing_tests_and_changed_files)
- [x] `route` resets the target stage and every later stage, and leaves earlier stages done. (test: factory/engine/tests/rework/test_rework.py::test_route_resets_the_target_stage_and_every_later_stage_and_leaves_earlier_stages_done)
- [x] Loop counters survive an engine restart. (test: factory/engine/tests/rework/test_rework.py::test_loop_counters_survive_an_engine_restart)
- [x] A rate-limit error is retried by `with_backoff` and never counts against task retries. (test: factory/engine/tests/rework/test_rework.py::test_a_rate_limit_is_retried_by_backoff_and_never_counts_against_task_retries)
- [x] Three failed tries put the run in `retrying` with the operation and start time in `run.json`; the next tick tries again and clears the state on success; after `infra_wait_hours` the run is blocked with an attention item. (test: factory/engine/tests/rework/test_rework.py::test_three_failed_tries_put_the_run_in_retrying_with_the_operation_and_start_time; factory/engine/tests/rework/test_rework.py::test_the_next_tick_tries_again_and_clears_the_state_on_success; factory/engine/tests/rework/test_rework.py::test_after_infra_wait_hours_the_run_is_blocked_with_an_attention_item; the same states driven through the engine at delivery: factory/engine/tests/engine/test_github_outage.py, six tests)
- [x] A feedback write that fails with an `OSError` waits as `retrying` with the operation named and no loop counted; the next pass writes one record in each task folder and reruns the stage; after `infra_wait_hours` the run is blocked; a schema failure still raises. (test: factory/engine/tests/engine/test_feedback_write_outage.py::test_a_feedback_write_that_fails_partway_waits_as_retrying_and_the_next_pass_routes_once; ::test_a_feedback_write_outage_blocks_the_run_only_after_infra_wait_hours_and_saves_no_route; ::test_a_schema_failure_in_the_feedback_record_still_raises_and_does_not_wait; ::test_a_human_rework_whose_feedback_write_fails_keeps_its_route_and_routes_on_the_next_pass; ::test_a_red_ci_feedback_write_that_fails_waits_and_the_next_pass_routes_once)
- [x] A gate, join, pre-push or red-CI rework whose feedback write failed is still routed when the next pass's check passes. The route is saved in `pending-route.json` (owner decision, 2026-11-25; section 18 unchanged), and the next pass applies it without running the check. (test: factory/engine/tests/engine/test_feedback_write_outage.py::test_a_gate_rework_whose_feedback_write_fails_is_still_routed_when_the_next_build_passes, ::test_a_red_ci_rework_whose_write_fails_is_still_routed_when_the_pull_request_reads_green, ::test_a_join_hook_that_fails_once_then_passes_is_still_routed_back_when_its_write_fails, ::test_a_pre_push_hook_that_fails_once_then_passes_is_still_routed_back_when_its_write_fails, ::test_a_saved_route_is_applied_once_however_many_passes_repeat_the_write, ::test_a_saved_route_is_not_applied_to_a_wait_on_another_operation; each fails on main or on the commit before its fix, checked by running it against that code)
- [x] `skip` passes only a gate marked `skippable: true`, requires a reason, logs `gate_skipped` and stops auto-merge; a gate not marked is refused and the run stays blocked. (test: factory/engine/tests/drivers/test_blocked_actions.py::test_skip_passes_a_skippable_gate_logs_the_reason_and_blocks_auto_merge; ::test_skip_refuses_a_gate_the_workflow_did_not_mark_skippable; ::test_skip_needs_a_reason; ::test_no_shipped_gate_is_skippable. Tested through `factory_engine.api`, not yet through the CLI, which module 16 has not built)
- [x] `retry` queues the note on the blocked stage's tasks and returns the run to running without changing loop counters; `goto` sends the run to an earlier stage and resets it; both refuse a run that is not blocked and a stage the workflow lacks. (test: factory/engine/tests/drivers/test_blocked_actions.py::test_retry_queues_the_note_and_moves_the_blocked_run_back_to_running; ::test_retry_refuses_a_run_that_is_not_blocked; ::test_goto_routes_a_blocked_run_to_an_earlier_stage_and_resets_it; ::test_goto_refuses_a_stage_the_workflow_does_not_have. Through `factory_engine.api` only)
- [x] A repo hook failing on the join commit or push is classified as rework, with the hook output in the feedback record; a hook failing on a network or missing-tool error is classified as transient. (test: factory/engine/tests/engine/test_repo_hooks_route.py::test_a_failing_repo_hook_on_the_join_commit_routes_the_run_back_to_implement, ::test_a_join_hook_that_fails_on_a_missing_tool_waits_for_infrastructure_and_is_not_rework, ::test_a_failing_pre_push_hook_routes_the_run_back_to_rework_and_does_not_crash_the_tick, ::test_a_pre_push_hook_that_fails_on_a_missing_tool_waits_for_infrastructure_and_is_not_rework; factory/engine/tests/gitops/test_gitops.py::test_a_failing_repo_hook_on_the_join_commit_returns_the_hooks_output; factory/engine/tests/rework/test_rework.py::test_a_join_hook_failure_carries_its_output_into_the_feedback_record, ::test_a_join_hook_failing_on_a_network_or_missing_tool_error_is_transient_and_a_defect_is_rework)

## Decisions

A row changes only through a new `proposed` ADR in `docs/adr/`. To read a folded ADR in full, see `docs/adr/README.md`; the Id cell is the file name without `.md`.

| Rule | Why | Not chosen | Id |
| --- | --- | --- | --- |
| A `cmd` task that exits non-zero is a check failure. The engine checks the binary first. Plugin scripts keep exit codes 0, 1 and 2. | `make`, `npm` and `pytest` all exit non-zero when a check fails, so this matches them and is simple to explain. The engine checks that the binary exists and starts first, so a non-zero exit means the check failed. | Each task declares its own fail and error codes (every workflow line gets longer, and it is easy to get wrong). Decide from the JUnit result (it does not cover lint or build commands). | 2026-11-14-cmd-task-non-zero-exit-is-a-check-failure (D2) |
| A verify stage whose tasks report 0 test cases together blocks the run (code `gate.no_test_results`) before a pull request opens. The block names the missing result files. | The factory must never open a pull request that says the tests passed when no test ran. | `pass-and-warn` (open the pull request with a warning line); `pass-silently` ("no tests ran" looks like "all passed"). | 2026-11-17-no-test-results-stops-the-run (T1) |
| `factory skip <run> --gate no-test-results` passes the T1 block, and only it. The blocked card shows this command, not `factory retry`. The engine accepts the name only when the latest `run_blocked` event has code `gate.no_test_results`. It turns off auto-merge. | The T1 block is raised by the engine in the verify join, so it is not a gate in the workflow. No workflow edit is needed and no shipped gate becomes skippable. | `skippable-test-report` (a skippable flag also lets a person skip real test failures); `has-test-results-check` (a new gate, which needs a workflow edit). | 2026-11-17-t1-skip-is-a-named-block-skip (T1) |
| The engine logs one `task_silent` event for a running `cmd` task whose `worker.log` has not grown for `stall_minutes` (default 10, 0 is off). It does not kill the task or change its state. Claude tasks are left out. Not built yet. | A task quiet on purpose, such as a compile that prints only at the end, would be killed and retried for nothing. Claude tasks need `stream-json` first. | `kill-on-silence` (end the attempt as `timeout`); `print-progress-in-commands` (cannot cover a repo's own commands). | 2026-11-18-a-silent-cmd-task-is-reported-not-killed (owner decision 2026-11-18) |
| A human's `rework` answer writes its notes as a feedback record (`gate: "human"`, `exit_code: null`, empty lists, the new optional `notes` field) into each task folder of the `on_reject.goto` stage, and logs `routed_back`, so the stage's next prompt shows them. A `reject` writes nothing. Rework with empty notes still writes the record, with `notes` empty. | The notes are the content of a human rework. Without them the stage runs again on the same input, so the loop cannot end for a reason the person cares about. The feedback path is the one channel a worker already reads for rework, so this is the smallest change that makes the rework row true. | Queue the notes as a note on each task (`notes.queue_note`): a task reset deletes `task.json`, the note API is built for a running task, and it loses the stage and loop context. Leave the row as it was and say the notes are not passed: a rework with no notes gives the worker nothing new. | 2026-11-22-human-rework-notes-reach-the-stage (owner answer, 2026-11-24, option 1) |
| After three tries the run is `retrying`. Each tick retries for `infra_wait_hours` (6) before the run is blocked. | Retries of 5 s, 30 s and 2 min block a run in a 3-minute outage, so one outage would block every active run and need a human for each. Waiting uses the existing tick, so no new loop is needed, and outages heal without human noise. | Keep the three tries and then block (many runs blocked by one outage). | 2026-11-14-outages-retry-then-block (D13) |
