---
scope: repo
repo: factory
topic: gc-keeps-a-branch-that-has-unpushed-commits
status: accepted
supersedes: []
---

# gc deletes a branch only when its commits are delivered somewhere

## Decision

Accepted by the owner on 2026-11-21, in the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them: fix `gc`'s branch deletion in the code.

`gc` deletes a run's branch only when it has no unpushed commits. A commit is unpushed when no remote-tracking ref has it and it is not on the base branch. A task branch the join applied is exempt, because its delivery is the join commit. A run branch whose pull request is merged is exempt, because the merge delivered it.

## Context

Before this change, `gc` ran `git branch -D` after removing a worktree, whether or not the branch had commits that no remote had. A run branch that was never pushed then lost its only copy of the work. The code is `_unpushed` and `_joined` in `housekeeping.py`; the rule is in module 17 under "Unpushed commits".

## Options considered

- **Fix the code (chosen).** Count unpushed commits before deleting, and keep the worktree and the branch when there are any.
  - The walkthrough's option list is not in the repo, so no alternatives are listed. This record states the answer the owner gave.

## Why

An unpushed branch cannot be recovered once deleted, and `gc` runs without a person watching.

## Consequences

- Tests: `test_a_run_branch_with_unpushed_commits_is_kept_and_reported`, `test_gc_keeps_an_unjoined_task_branch_with_commits_and_deletes_a_joined_one`, `test_a_run_branch_whose_commits_are_on_a_remote_ref_is_deleted`, `test_cleanup_after_merge_deletes_a_run_branch_whose_commits_a_squash_merge_delivered`, all in `factory/engine/tests/housekeeping/test_housekeeping.py`.
- A branch is kept when git cannot count its commits. The skip names the branch and says to push it or delete it by hand.
- Commit `6a69067`, PR #73.

## Source

Written on 2026-11-21 by Claude Code from the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them. The answer is the owner's, not new.
