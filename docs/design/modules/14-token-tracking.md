# 14. Module: token tracking

Part of the [phase 1 design](../phase-1.md#module-map). Build wave: 1. Contracts and acceptance criteria are in this file; shared types are in [section 18](../shared/18-shared-contracts.md). Terms such as run, stage, task, attempt and rework are defined in the [glossary](../phase-1.md#2-glossary).

Budget caps are on hold (KIV) because they need reliable token counts in the middle of a run. Instead, every attempt is tracked, so the data exists when caps are added. Timeouts, helper maximums and restart caps still apply, because they are counts and timers, not spend.

| Field in `tasks/<task>/usage.jsonl` | Meaning |
| --- | --- |
| `model_requested` | The model the engine asked for, or `null` when it sent none |
| `models` | The model names the harness reported for the attempt, such as `["claude-opus-5-5"]`; `[]` when it reported none |
| `harness` | The CLI that ran it |
| `input_tokens`, `output_tokens`, `total_tokens` | Tokens used; `null` when the harness did not report them, never 0 |
| `start`, `end`, `exit` | Timestamps, and `ok`, `failed` or `interrupted` |
| `repo`, `branch`, `worktree` | Where the work happened; the branch is the run id |
| `run_id`, `task_id`, `stage`, `attempt` | Which attempt of which task |

- **Durable:** the record is written as `started` before the worker launches, then a full `ended` line is appended, and the last line for an attempt wins. An attempt cut off by a crash is closed as `interrupted`, with no token count.
- **Reports:** `factory usage [run] [--repo] [--since]` prints totals per model: attempts, tokens, attempts with no count, minutes. The dashboard and the run summary show the same totals.
- Token counts and model names come from what the CLI reports, never from config. Reports group by the observed model; an attempt with no observed model is grouped as `unknown`, and an attempt with several models is counted under each, with tokens split as the harness reported them.

**Module contract: 14 Token tracking**

- **Depends on:** 6A: `task_dir`, `append_event`.
- **Writes:** `usage.jsonl`; events `attempt_started`, `attempt_ended`.
- **CLI it backs:** `usage`.

```python
# usage.py
def start_attempt(run_dir: Path, run: Run, task_id: str, *, stage: str, harness: str,
                  model_requested: str | None) -> int
def finish_attempt(run_dir: Path, task_id: str, attempt: int, *, exit: str,
                   input_tokens: int | None, output_tokens: int | None,
                   models: list[str]) -> None
def close_open_attempts(run_dir: Path) -> list[tuple[str, int]]   # mark interrupted after a crash
def read_usage(run_dir: Path, task_id: str) -> list[UsageRecord]
def summarize(run_dirs: list[Path], *, since: date | None = None) -> UsageReport   # per observed model, repo, day
```

- **Run and test:** `pytest factory/engine/tests/usage`; `factory usage --json`.
- **Errors:** missing or unreadable usage is recorded as `null` with a warning, and never blocks.

Acceptance criteria:

- [x] A started record exists before the worker launches; the ended record holds the requested model, the observed models, tokens, start, end, repo, branch and worktree. (test: factory/engine/tests/usage/test_usage.py::test_a_started_record_exists_before_the_worker_launches_and_the_ended_record_holds_the_facts)
- [x] An attempt with no requested model records `model_requested: null` and the observed models from the result. (test: factory/engine/tests/usage/test_usage.py::test_an_attempt_with_no_requested_model_records_the_observed_models_from_the_result)
- [x] Unknown tokens are `null`, never 0, and are counted separately in reports. (test: factory/engine/tests/usage/test_usage.py::test_unknown_tokens_are_null_never_zero_and_counted_separately)
- [x] `close_open_attempts` marks every open attempt `interrupted`. (test: factory/engine/tests/usage/test_usage.py::test_close_open_attempts_marks_every_open_attempt_interrupted_with_no_count)
- [x] Reports group by observed model, repo and day; an attempt with no observed model is under `unknown`. (test: factory/engine/tests/usage/test_usage.py::test_reports_group_by_observed_model_repo_and_day_with_unknown_for_no_model)
