---
scope: repo
repo: factory
topic: checkpoint-commits-stay-local
status: accepted
supersedes: []
---

# Commits the engine makes without a request

## Decision

Checkpoints stay on a local task branch that is never pushed; only the join commit is pushed. No switch to turn them off, because D12 recovery and note delivery need them

Chosen option: `local-branch`.

## Context

Checkpoints are WIP commits on a task branch. They also drive crash recovery (resume from the last checkpoint), note delivery (restart at a checkpoint) and the D12 reset target. The repo rule forbids committing unless asked.

## Options considered

- **`local-branch`** (chosen) (recommended): Keep checkpoints on a local task branch that is never pushed; only the join commit is pushed
  - For: Crash recovery and notes keep working
  - For: Task branches are already never pushed in the spec
  - For: The pushed history is one commit per task
  - Against: Still creates local commits the repo rule did not ask for
  - Against: Needs the owner to accept 'the engine commits locally' as a request
- **`no-commits`**: Turn checkpoints off in this repo; snapshot with a stash or a patch file instead
  - For: No commit the owner did not request
  - For: Matches the repo rule literally
  - Against: A new engine path to build and test for one repo
  - Against: Recovery and the D12 reset must use patches, which merge badly
  - Against: Not in phase 1a scope
- **`ask-once`**: Record the owner's request once in the repo config and treat it as the request for all checkpoint commits
  - For: Smallest change
  - For: Keeps the standard engine path
  - For: The consent is written down and reviewable
  - Against: Interprets the repo rule loosely; the owner must agree that it counts

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

Checkpoints carry three features, so removing them costs more than keeping them local.

## Source

Backfilled on 2026-11-16 from `docs/reviews/phase-1-decisions.md`, decision `P1`, page `docs/reviews/pilot-repo-decisions.json`. The owner chose this on 2026-11-14; the answer is the record's, not new.
