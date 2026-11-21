---
scope: repo
repo: factory
topic: usage-reads-the-last-whole-line-for-each-attempt
status: accepted
supersedes: []
---

# Usage reads skip unreadable lines and keep the last whole line for each attempt

## Decision

Accepted by the owner on 2026-11-21, in the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them: fix the usage reading bugs in the code.

A line is readable when it is a whole JSON object with an integer `attempt` and every field of `UsageRecord`. Reads skip the others and go on. The last readable line for an attempt wins, even when an unreadable line comes after it. A record written after a torn last line starts on a new line. `start_attempt` never gives out a number it saw in an unreadable line.

## Context

The calibration found that a line with no `attempt` number raised `KeyError` in `read_usage` and `close_open_attempts`; that the next record after a torn line was joined to it and lost; and that a number seen only in an unreadable line could be given out again. Module 14 says unreadable usage never blocks. The code is `_read`, `_append` and `start_attempt` in `usage.py`.

## Options considered

- **Fix the code (chosen).** Read what is whole, skip what is not, and never reuse a number.
  - The walkthrough's option list is not in the repo, so no alternatives are listed. This record states the answer the owner gave.

## Why

Usage is written before the worker starts and read after a crash, so a torn write must not hide the attempt.

## Consequences

- Tests in `factory/engine/tests/usage/test_usage.py`: `test_a_line_with_no_attempt_number_is_skipped_and_the_read_goes_on`, `test_a_record_after_a_torn_line_starts_on_a_new_line_and_its_attempt_finishes`, `test_an_unreadable_last_line_does_not_hide_an_earlier_whole_line_for_the_attempt`, `test_start_attempt_does_not_reuse_a_number_seen_in_an_unreadable_line`.
- Commit `6a69067`, PR #73.

## Source

Written on 2026-11-21 by Claude Code from the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them. The answer is the owner's, not new.
