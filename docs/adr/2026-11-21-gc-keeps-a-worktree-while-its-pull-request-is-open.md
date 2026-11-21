---
scope: repo
repo: factory
topic: gc-keeps-a-worktree-while-its-pull-request-is-open
status: accepted
supersedes: []
---

# gc keeps a run's worktree and branch while its pull request is open

## Decision

Accepted by the owner on 2026-11-21, in the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them: keep a worktree while its pull request is open.

`gc` reads the state of a run's pull request through a `prs` argument. Open: the worktree and branch are kept and the skip says "pull request open". Merged: both are removed. Closed: both go by the unpushed rule. Unreadable, or no `prs` given: both are kept and the skip says why. The run is archived either way. A run with no pull request is not held.

## Context

`gc` had no pull request state, so a `done` run's worktree went with its archive, even when review was still open. `api.gc` passed no client to `housekeeping.plan`, so `factory gc` kept every run that had a pull request. The wiring is `prs=default_prs(repo, cfg)` in `api.py`.

## Options considered

- **Hold the worktree while the pull request is open (chosen).**
  - The walkthrough's option list is not in the repo, so no alternatives are listed. This record states the answer the owner gave.

## Why

The worktree and branch hold the work under review. Deleting them while the pull request is open removes the place where a review comment would be fixed.

## Consequences

- Tests: `test_an_open_pull_request_keeps_the_worktree_until_it_is_merged`, `test_a_closed_pull_request_lets_the_worktree_go`, `test_a_pull_request_that_cannot_be_read_keeps_the_worktree_and_says_why`, `test_a_run_without_a_pull_request_is_not_held_by_gc`, and `test_api_gc_asks_the_pull_request_client_so_a_merged_pr_frees_the_worktree`, which fails when the `api.py` argument is removed.
- **Not tested against GitHub.** Every test uses `FakePullRequests`. Task 34 stays open until `factory gc` runs on a repo with an open, a merged and a closed pull request.
- Commit `6a69067`, PR #73.

## Source

Written on 2026-11-21 by Claude Code from the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them. The answer is the owner's, not new.
