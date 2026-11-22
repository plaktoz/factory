# 14. Module: token tracking

Part of the [phase 1 design](../phase-1.md#module-map). Build wave: 1. Contracts and acceptance criteria are in this file; shared types are in [section 18](../shared/18-shared-contracts.md). Terms such as run, stage, task, attempt and rework are defined in the [glossary](../phase-1.md#2-glossary).

Budget caps are on hold (KIV) because they need reliable token counts in the middle of a run. Instead, every attempt is tracked, so the data exists when caps are added. Timeouts, helper maximums and restart caps still apply, because they are counts and timers, not spend.

| Field in `tasks/<task>/usage.jsonl` | Meaning |
| --- | --- |
| `model_requested` | The model the engine asked for, or `null` when it sent none |
| `models` | The model names the harness reported for the attempt, such as `["claude-opus-5-5"]`; `[]` when it reported none |
| `harness` | The CLI that ran it |
| `input_tokens`, `output_tokens`, `total_tokens` | Tokens used, summed over the models the harness reported (module 9). The harness reports the two counts only. The engine sets `total_tokens` in `finish_attempt` as the sum of the two counts, and a `null` count adds nothing. A count the harness did not report is `null`, never 0; `total_tokens` is `null` only when both counts are |
| `start`, `end`, `exit` | Local times with the UTC offset, to the second. `start` is set when the attempt starts, and `end` when it is finished or closed. `exit` is `started` while the attempt is open, then `ok`, `failed` or `interrupted` |
| `repo`, `branch`, `worktree` | Where the work happened; the branch is the run id |
| `run_id`, `task_id`, `stage`, `attempt` | Which attempt of which task |

- **Durable:** the record is written as `started` before the worker launches, then a full `ended` line is appended, and the last line for an attempt wins. An attempt cut off by a crash is closed as `interrupted`, with no token count.
- **Exit values:** the engine sets `exit` from the worker's result. It is `ok` when the worker exited ok and left its artifact. It is `interrupted` when the worker was killed (module 9), or was stopped to take a note and did not finish ok. It is `failed` in every other case, including a `timeout` (module 9), a result with no artifact, and a crash. A resume after a crash, a stop, or `recover` closes each open attempt as `interrupted`.
- **Reports:** `factory usage [run] [--repo] [--since]` prints the by-model rows under the label "per model, an attempt with several models is counted under each", then one total row that counts each attempt once. Each row shows attempts, tokens, attempts with no count, minutes. `--json` prints four groups: `by_model`, `by_repo`, `by_day` and `total`. The dashboard shows the by-model, by-repo and by-day groups, and the run summary shows the by-model rows.
- Token counts and model names come from what the CLI reports, never from config. Reports group by the observed model; an attempt with no observed model is grouped as `unknown`. An attempt with several models is counted once under each model, and its full summed tokens and its minutes are added under each. The model rows therefore add up to more than the real total, and tokens are not split per model, because the record holds one summed count. Repo and day groups count each attempt once.

**Module contract: 14 Token tracking**

- **Depends on:** 6A: `task_dir`, `append_event`.
- **Writes:** `usage.jsonl`; events `attempt_started`, `attempt_ended`, `usage_unreadable`.
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
- **Report types:** `ModelTotals` has `attempts`, `input_tokens`, `output_tokens` and `total_tokens` (sums over the attempts that have a count), `attempts_without_count` (attempts where both counts are `null`) and `minutes` (a float). `UsageReport` has `by_model`, `by_repo` and `by_day`, each a dict from a key to a `ModelTotals`, and `total`, one `ModelTotals` that counts each attempt once. The keys are the observed model name (`unknown` when there is none), the repo folder name, and the start day as `YYYY-MM-DD`. Open (`started`) attempts are left out of every total.
- **Numbering:** `start_attempt` gives an attempt one more than the highest attempt number among the readable lines of the task and the unreadable lines whose number can be read. A task's first attempt is 1, and numbers carry on across restarts and resumes. A number seen in an unreadable line is never given out again. A number is read from the JSON of a whole line, or from the text of a torn line.
- **Timestamps:** `start` is the local time when `start_attempt` writes the `started` record. `end` is the local time when `finish_attempt` or `close_open_attempts` writes the `ended` line. Both are read from the system clock, not from the injected clock of module 6, and are written to the second, with the UTC offset.
- **Days and `--since`:** an attempt belongs to the day in its `start`, as written with its own offset. `summarize` with `since` leaves out attempts that start before that day. There is no end date. The CLI reads `--since` as `YYYY-MM-DD`.
- **Minutes:** `end` minus `start`, for each attempt with an `end`, never below 0. An `interrupted` attempt's `end` is the time its close ran, so its minutes include the time since the crash. A multi-model attempt adds its minutes under each of its models, as it does its tokens, so minutes in the model rows overlap.
- **Reads:** `read_usage` returns a list of the shared `UsageRecord` (section 18), sorted by attempt number, with one entry per attempt. Each entry comes from the last readable line for that attempt. A line is readable when it is a whole JSON object with an integer `attempt` and every field of `UsageRecord`. The `schema_version` key is dropped and `worktree` is a path. An open attempt comes back with `exit` `started`. A task with no `usage.jsonl` gives an empty list.
- **Errors:** missing or unreadable usage is recorded as `null` with a warning, and never blocks. A count the harness did not report stays `null`. A torn line, one with no newline or that is not JSON, is skipped, as the module 6 rule for `.jsonl` files says. A whole line that lacks a field of `UsageRecord`, or has no `attempt` number, is left out of reads. Such a line is not a record, so it is not counted under `attempts_without_count`; `start_attempt` reports it (see failure behaviour).
- **Failure behaviour:**
  - A `started` write that fails raises to the caller before the worker starts, so no worker launches.
  - An `ended` write that fails raises before the task state and its checkpoint are written. The attempt stays `started` on disk until the next resume closes it as `interrupted`, with no count.
  - An `exit` that is not `ok`, `failed` or `interrupted` raises `config.invalid`. So does `finish_attempt` for an attempt with no `started` line. Both write nothing.
  - `finish_attempt` for an attempt that already has an `ended` line appends another. The last line wins, and no error is raised.
  - An unreadable line, including one with no `attempt` number, is skipped by `read_usage` and `close_open_attempts`. The read goes on and does not raise.
  - A record written after a torn last line starts on a new line. The torn line is skipped, and the new record is read, so its attempt can finish.
  - When the last line for an attempt is unreadable, the last readable line for that attempt is used. An unreadable line never hides an earlier whole line.
  - `start_attempt` writes one `usage_unreadable` event for each unreadable line, with the task id and the line number, to the run's `events.jsonl`. Each line is reported once, so later starts do not repeat it. Read paths (`read_usage`, `summarize`) write nothing.

Acceptance criteria:

- [x] A started record exists before the worker launches; the ended record holds the requested model, the observed models, tokens, start, end, repo, branch and worktree. (test: factory/engine/tests/usage/test_usage.py::test_a_started_record_exists_before_the_worker_launches_and_the_ended_record_holds_the_facts)
- [x] An attempt with no requested model records `model_requested: null` and the observed models from the result. (test: factory/engine/tests/usage/test_usage.py::test_an_attempt_with_no_requested_model_records_the_observed_models_from_the_result)
- [x] Unknown tokens are `null`, never 0, and are counted separately in reports. (test: factory/engine/tests/usage/test_usage.py::test_unknown_tokens_are_null_never_zero_and_counted_separately)
- [x] `close_open_attempts` marks every open attempt `interrupted`. (test: factory/engine/tests/usage/test_usage.py::test_close_open_attempts_marks_every_open_attempt_interrupted_with_no_count)
- [x] Reports group by observed model, repo and day; an attempt with no observed model is under `unknown`. (test: factory/engine/tests/usage/test_usage.py::test_reports_group_by_observed_model_repo_and_day_with_unknown_for_no_model)
- [x] A read of the usage file returns the last line for each attempt, and the attempt numbers continue from it. (test: factory/engine/tests/usage/test_usage.py::test_the_last_line_for_an_attempt_wins_and_attempts_are_numbered)
- [x] A report with `--since` leaves out attempts that start before that day. (test: factory/engine/tests/usage/test_usage.py::test_a_report_with_since_leaves_out_attempts_that_start_before_that_day)
- [x] An attempt with several models is counted under each model, with its summed tokens and minutes. (test: factory/engine/tests/usage/test_usage.py::test_an_attempt_with_several_models_is_counted_under_each)
- [x] A line with no `attempt` number is skipped by reads, and the read goes on. (test: factory/engine/tests/usage/test_usage.py::test_a_line_with_no_attempt_number_is_skipped_and_the_read_goes_on)
- [x] A record written after a torn last line starts a new line, and its attempt finishes. (test: factory/engine/tests/usage/test_usage.py::test_a_record_after_a_torn_line_starts_on_a_new_line_and_its_attempt_finishes)
- [x] An unreadable last line does not hide the attempt's earlier whole line. (test: factory/engine/tests/usage/test_usage.py::test_an_unreadable_last_line_does_not_hide_an_earlier_whole_line_for_the_attempt)
- [x] Attempt numbers never reuse a number seen in an unreadable line. (test: factory/engine/tests/usage/test_usage.py::test_start_attempt_does_not_reuse_a_number_seen_in_an_unreadable_line)
- [x] `start_attempt` writes one `usage_unreadable` event per unreadable line, with the task id and line number. (test: factory/engine/tests/usage/test_usage.py::test_start_attempt_writes_one_usage_unreadable_event_per_line_with_the_task_and_line)
- [x] Read paths write no events. (test: factory/engine/tests/usage/test_usage.py::test_read_paths_write_no_events)
- [x] The report total counts an attempt with several models once. (test: factory/engine/tests/usage/test_usage.py::test_the_total_counts_an_attempt_with_several_models_once)
- [x] `factory usage` labels the by-model rows as per model, and prints the total. (test: factory/engine/tests/usage/test_usage.py::test_factory_usage_labels_the_model_rows_and_prints_the_total)
- [x] `factory usage --json` carries the `total` group. (test: factory/engine/tests/usage/test_usage.py::test_factory_usage_json_carries_the_total)

## Choices made where this file was silent (2026-11-21, issue 55)

- The warning for an unreadable line is a `usage_unreadable` event in the run's `events.jsonl`, written by `start_attempt`, which already reads the whole task file. Read paths write nothing.
- The `usage_unreadable` event carries the task id and the line number, and is listed in the Writes line of the contract.
- The event is written once per line: a later `start_attempt` for the same task does not repeat it for a line already reported.
- A torn last line is ended with a newline by the next append, so the new record is not joined to it. The torn line stays in the file and is skipped.
- The `total` group in `UsageReport` is a new field. It is the only report field the spec did not list, and no shared contract or schema lists `UsageReport` fields.

## Decisions

A row changes only through a new `proposed` ADR in `docs/adr/`. To read a folded ADR in full, see `docs/adr/README.md`; the Id cell is the file name without `.md`.

| Rule | Why | Not chosen | Id |
| --- | --- | --- | --- |
| Leave `model` unset and store the models the harness result reports as the observed models. | The usage record is for facts, so it keeps what the harness reported. | `label`: a fixed label from repo config. It can hide a real model change. | `2026-11-14-record-the-model-the-harness-reports` (P4) |
| An attempt with several models is counted once under each model, with its full summed tokens and minutes. `factory usage` labels the model rows and prints one total that counts each attempt once. | A split would show numbers the harness did not report. | No other option is recorded. | `2026-11-21-keep-the-multi-model-double-count-and-label-it` (owner decision 2026-11-21) |
| `start_attempt` writes one `usage_unreadable` event for each unreadable usage line, with the task id and line number. Each line is reported once. Read paths write nothing. | A skipped line is lost data, and the run's record should show it. | No other option is recorded. | `2026-11-21-keep-the-usage-unreadable-event` (owner decision 2026-11-21) |
| Reads skip unreadable lines. The last readable line for an attempt wins. A record after a torn line starts on a new line. A number seen in an unreadable line is never given out again. | Usage is written before the worker starts and read after a crash, so a torn write must not hide the attempt. | No other option is recorded. | `2026-11-21-usage-reads-the-last-whole-line-for-each-attempt` (owner decision 2026-11-21) |
