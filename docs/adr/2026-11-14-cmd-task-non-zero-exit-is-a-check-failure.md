---
scope: repo
repo: factory
topic: cmd-task-non-zero-exit-is-a-check-failure
status: accepted
supersedes: []
---

# Exit codes

## Decision

A `cmd` task exiting non-zero is a check failure; the engine checks the binary first. Plugin scripts keep 0, 1, 2

## Source

Backfilled on 2026-11-16 from `docs/reviews/phase-1-decisions.md`, decision `D2`. The owner chose this on 2026-11-14; the answer is the record's, not new.
