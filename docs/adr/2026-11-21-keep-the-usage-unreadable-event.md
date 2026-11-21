---
scope: repo
repo: factory
topic: keep-the-usage-unreadable-event
status: accepted
supersedes: []
---

# An unreadable usage line is reported as a `usage_unreadable` event

## Decision

Accepted by the owner on 2026-11-21, in the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them: keep the `usage_unreadable` event.

`start_attempt` writes one `usage_unreadable` event for each unreadable line of a task's usage file, with the task id and the line number, to the run's `events.jsonl`. Each line is reported once. Read paths write nothing.

## Context

Module 14 said unreadable usage is recorded as `null` "with a warning" and named no place for the warning. `start_attempt` already reads the whole task file, and the run's event log is where the other facts of a run are written.

## Options considered

- **Keep the event (chosen).** Listed in the contract's Writes line.
  - The walkthrough's option list is not in the repo, so no alternatives are listed. This record states the answer the owner gave.

## Why

A skipped line is lost data, and the run's record should show that it happened.

## Consequences

- Tests: `test_start_attempt_writes_one_usage_unreadable_event_per_line_with_the_task_and_line` and `test_read_paths_write_no_events`.
- Not covered: reports (`factory usage`) do not mention skipped lines, because read paths write nothing.
- Commit `6a69067`, PR #73.

## Source

Written on 2026-11-21 by Claude Code from the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them. The answer is the owner's, not new.
