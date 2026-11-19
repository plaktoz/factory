---
scope: repo
repo: factory
topic: a-silent-task-is-reported-as-stalled
status: accepted
supersedes: [2026-11-17-a-silent-task-is-reported-as-stalled]
---

# A silent `cmd` task is reported, not killed

## Decision

Accepted by the owner on 2026-11-18: option `report-silence-as-an-event`, for `cmd` tasks only, with a default of 10 minutes.

The engine notes when a running `cmd` task's `worker.log` last grew. After `stall_minutes` with no growth, it logs one `task_silent` event and shows it on the task card. `stall_minutes` is a task field: the default is 10, and 0 turns the check off. The engine does not kill the task or change its state. A person decides what to do.

This supersedes `2026-11-17-a-silent-task-is-reported-as-stalled`, which proposed the option for every task. That ADR was written by another agent run and lives on the unpushed branch `wave4/observable-long-runs` (commit `c440f93`). Its context and the two rejected options are summarized below.

## Context

A task has one time limit, `timeout_minutes`, which ends it after that many minutes in total (module 5). A task that hangs at minute 2 of a 60 minute limit looks the same as one that is working. This applies to the factory's own runs and to any app a workflow builds, because any `cmd` task can run a long step, such as a test suite, a build or a migration.

The check needs `worker.log` to grow while the task runs. `2026-11-17-worker-log-is-written-while-the-task-runs` (accepted, merged in PR #57) does that.

## Why `cmd` tasks only

Claude workers run with `--output-format json`, so their live `worker.log` holds stderr only until the attempt ends. A check on every task would report every long Claude task as silent. Covering Claude tasks needs `stream-json`, which changes result parsing and is a separate decision. Codex tasks are also left out until their live log is checked.

## Rejected options

- **`kill-on-silence`**: end the attempt as `timeout` so the retry rules run. Rejected: a task that is quiet on purpose, such as a compile that prints only at the end, would be killed and retried for nothing, and each retry costs money.
- **`print-progress-in-commands`**: no engine change; the shipped commands print progress. Rejected as the only fix: it cannot cover a command that a repo supplies. Shipped commands should still print progress where they can, as the test command does (`[done/total]`).

## Consequences

- `workflow.schema.json`: the `task` definition gains `stall_minutes` (integer, at least 0, default 10). The `TaskSpec` dataclass mirrors it.
- Module 5 gets a line on `stall_minutes`, module 12 gets the card line, and module 6 adds `task_silent` to its event list.
- The check runs in the engine's existing poll loop, in the process that holds the run lock. It needs no new thread.
- Known limit: only complete lines are copied into `worker.log`, so a command that prints progress dots on one line does not grow the log until its newline.
- Tests: a fake `cmd` worker that goes quiet gets exactly one `task_silent` event; one that keeps printing gets none; `stall_minutes: 0` gets none; a Claude task gets none.
- Not built yet. Building it is a separate task.
