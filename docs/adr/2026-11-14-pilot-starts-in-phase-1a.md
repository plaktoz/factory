---
scope: repo
repo: factory
topic: pilot-starts-in-phase-1a
status: accepted
supersedes: []
---

# When the pilot starts

## Decision

Phase 1a, with one chore or bug-fix issue and a human merge; feature work in 1b

Chosen option: `1a-chore`.

## Context

The repo's open tasks are jest feature work, which needs the 1b feature workflow. A chore or bug-fix pilot could run on phase 1a.

## Options considered

- **`1a-chore`** (chosen) (recommended): Start in phase 1a with one chore or bug-fix issue, human merge, then move to feature work in 1b
  - For: Real feedback on the core loop early
  - For: Small blast radius
  - For: Tests the repo constraints before feature work
  - Against: Needs a suitable chore or bug in the repo
  - Against: Pilot results arrive before the dashboard has writes
- **`after-1b`**: Wait for phase 1b and start with a feature task
  - For: Matches the repo's real backlog
  - For: One start, no rework of constraints
  - Against: No real-repo feedback for the whole of 1a
  - Against: Constraint conflicts surface late

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

The riskiest assumptions are the repo constraints, and a chore tests them cheaply.

## Source

Backfilled on 2026-11-16 from `docs/reviews/phase-1-decisions.md`, decision `P3`, page `docs/reviews/pilot-repo-decisions.json`. The owner chose this on 2026-11-14; the answer is the record's, not new.
