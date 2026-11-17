---
scope: repo
repo: factory
topic: cleanup-runs-repo-comparison-first
status: accepted
supersedes: []
---

# Run state and worktrees against the repo's worktree rule

## Decision

Cleanup runs the repo's `cleanup_check` first and skips removal when it fails

Chosen option: `gate-cleanup`.

## Context

The repo says work stays in the worktree until git status is clean, and a worktree is removed only after a comparison. The engine removes task worktrees right after the join and the run worktree after merge.

## Options considered

- **`gate-cleanup`** (chosen) (recommended): Make cleanup run the repo's comparison first and skip removal when it fails
  - For: Follows the repo's rule
  - For: Housekeeping already skips dirty worktrees
  - For: Leaves a report when it skips
  - Against: Needs the comparison as a configurable command per repo
  - Against: Leftover worktrees pile up until someone clears them
- **`keep-all`**: Never remove worktrees in this repo; the owner runs gc by hand
  - For: Nothing removed by surprise
  - For: No new code
  - Against: Disk and branch clutter grows
  - Against: Defeats the end-of-life promise in the spec

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

The spec already skips dirty worktrees, so one more gate is a small step.

## Source

Backfilled on 2026-11-16 from `docs/reviews/phase-1-decisions.md`, decision `P2`, page `docs/reviews/pilot-repo-decisions.json`. The owner chose this on 2026-11-14; the answer is the record's, not new.
