# 8. Module: gates, error handling and rework

Part of the [phase 1 design](../phase-1.md#module-map). Build wave: 2. Contracts and acceptance criteria are in this file; shared types are in [section 18](../shared/18-shared-contracts.md). Terms such as run, stage, task, attempt and rework are defined in the [glossary](../phase-1.md#2-glossary).

The engine sorts every failure into one class, and each class has a fixed response. A failed gate routes the run back to an earlier stage with a feedback record. When retries or loops run out, the run is blocked and shown under Needs you.

| Class | Examples | Engine response | Limit |
| --- | --- | --- | --- |
| Worker error | Crash, non-zero exit, timeout, no artifact, artifact fails its schema | Retry the same task from its last checkpoint as a new attempt | `retries` per task (default 2) |
| Infrastructure error | Git lock file, network, GitHub rate limit, disk full | Retry the operation with backoff (waits of 5 s and 30 s between three tries). The worker never sees it | 3 tries, then the run waits as `retrying` and each tick tries again until `infra_wait_hours` (default 6) pass, then blocked |
| Gate failure | Tests fail (a `cmd` task exits non-zero), scope violation, blocking review finding | Rework: route to `on_fail.goto` with a feedback record | `on_fail.max` loops per edge |
| Merge conflict at join | Two task branches change the same lines | Abort the merge, route to `on_conflict.goto` | `on_conflict.max` |
| Human rework | You answer rework at an approval | Route to `on_reject.goto` with your notes as feedback | None |
| Human reject | You answer reject | Run aborted | None |
| Engine crash | Process killed, machine asleep | On the next start, open attempts become interrupted and resume | Does not use retries; `max_interruptions` per task (default 3), then the task is failed |

**Rework, step by step** (verify fails in a bug-fix run)

1. Task `be-tests` (`make test-api`) exits non-zero. For a `cmd` task that is a check failure, so the stage's `on_fail` applies. The engine logs `gate_failed`.
2. It writes a feedback record into the fix stage's task folders and logs `routed_back` with `verify->fix` loop 1 of 3.
3. Stages from fix onward reset to pending. Earlier stages stay done. The run branch keeps its commits, so fix continues from the current code rather than starting over.
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

- `factory retry <run> [--stage <s>] [--note "..."]` runs the stage again once more, with your note added to the feedback.
- `factory goto <run> <stage>` routes the run to any earlier stage.
- `factory skip <run> --gate <id> --reason "..."` passes a gate marked `skippable: true`. It is logged, and the run can no longer be auto-merged.
- `factory abort <run>` stops the run, and housekeeping cleans it up.

**On the dashboard**

- The run row turns amber while reworking and red when blocked or failed.
- The stage strip draws the loop back, such as `verify → fix 1/2`.
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
- **Decisions taken while building (wave 2).** The 2 min step of the backoff is not used: three tries have two waits, so the list is `(5, 30)`, and the 2 min step needs a decision on where it goes. A `cmd` task's non-zero exit is a gate failure, so 6B passes its result to `cmd_gate_result`; `classify` alone reads a bare non-zero exit as a worker error. `max` is the number of loops an edge allows: `max: 3` routes the first three failures and blocks the fourth. The module 5 workflow examples use `max` values of 1 and 2, and the bug-fix walkthrough now uses 3 as the decided value. A gate command that is missing is `gate.command_missing`, kind `human`, as module 9 gives a missing binary.

**Gate commands run sandboxed.** A `cmd` gate such as `[make, build]` runs through `CommandAdapter`, so it runs under `srt` with the worker's read and write rules ([module 9](09-worker-adapters-and-governed-helpers.md)). A gate that needs a domain or a cache folder gets them the way a task does. The exit code is the one the command returned: 0 passes, any other value is a gate failure, and a missing binary or a sandbox that cannot start is a task error, not a gate failure.

Acceptance criteria:

- [ ] Each failure type in the class table maps to exactly one handling type.
- [ ] A `cmd` gate runs under `srt`; its exit code decides pass or fail, and a missing binary is a task error.
- [ ] Gates stop at the first failure and return the output tail.
- [ ] A feedback record holds the gate, exit code, failing test names and changed files, all taken from command output.
- [ ] `route` resets the target stage and every later stage, and leaves earlier stages done.
- [ ] Loop counters survive an engine restart.
- [ ] A rate-limit error is retried by `with_backoff` and never counts against task retries.
- [ ] Three failed tries put the run in `retrying` with the operation and start time in `run.json`; the next tick tries again and clears the state on success; after `infra_wait_hours` the run is blocked with an attention item.
- [ ] A repo hook failing on the join commit or push is classified as rework, with the hook output in the feedback record; a hook failing on a network or missing-tool error is classified as transient.
