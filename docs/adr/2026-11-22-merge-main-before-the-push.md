---
scope: repo
repo: factory
topic: merge-main-before-the-push
status: accepted
supersedes: []
---

# The branch is merged with origin/main before it is pushed, and the merge is recorded

## Decision

Accepted by the owner on 2026-11-22, on the page "Pilot start and the push" (`.scratch/pilot-and-push.json`, since deleted; its answers are in these records), decision `D3`: option `merge-main`, the recommended option. The session fetched `origin/main` and merged it into `plaktoz/proposal-standardized-spec-adr-scoring-rubric-re`, then recorded the merge. The branch is not pushed yet; that is D7, which waits on the pilot table (task 37).

## Context

The owner asked for this with the words "go". The repo rules reserve fetch and merge of `main` for when the owner asks, so this was the one time it was done.

What the fetch found, checked by running `git`:

- `origin/main` had moved past `7d6d051`, the sha the branch was based on. It is now `13ab255` (PR #84, `plaktoz/pilot-setup`), with PR #81 (the new-project tutorial) and PR #83 (`dashboard --detach`) before it.
- The merge had one conflict, in `docs/tasks.md`: the state paragraph's `main` sha, and the log. Both sides were kept. The sha now names `13ab255`, and the log lines of both sides are in the file, newest first.
- `main` had already filled in the pilot table (`docs/setup/spec-workflow-pilot.md`), with the owner, the start day and the baselines. It named two pilot tickets that were drafts. D1 replaces those drafts with #88 and #89, so the two rows now link to those issues.
- `main`'s baseline note said the first-approval review measure "has no value". D2 changed the measure, so the note now says so too.

Checks on the merged tree, run on 2026-11-22:

- `python3 -I scripts/docs-check/records.py .`: 0 problems.
- `python3 -I scripts/docs-check/links.py .`: 235 links, 0 broken.
- `pytest tests` in `factory/launcher`, serially: 126 passed.
- `pytest tests/engine tests/drivers tests/workflow` in `factory/engine`, `-n 8`: 191 passed, 1 warning.

The warning is a worker thread that raised `git.command_failed`: `git diff --binary: bad revision 'bump-q1w2e...bump-q1w2e--a'`, in `test_a_task_whose_when_does_not_hold_is_skipped_and_the_stage_still_finishes`. The same test on `13ab255`, before this merge, gives the same warning, so the merge did not cause it. The test passes, so the error is swallowed by the engine. It is recorded as a new task, not fixed here.

A `-n 8` launcher run failed before running any tests, and the serial run passed. The cause was not investigated.

## Options considered

- **`merge-main`** (chosen, recommended): fetch and merge `origin/main`, then push as one pull request.
  - For: matches how the earlier pull requests went in, and the one conflict is fixed here where the records check runs.
  - Against: adds a merge commit, and the tasks file needed a hand fix.
- **`fresh-branch`** (not chosen): copy the new commits onto a new branch from `main`.
  - For: the smallest pull request, and no merge commit.
  - Against: the branch name changes from the one earlier pull requests used, and each commit may conflict on the tasks file.
- **`push-as-is`** (not chosen): push without merging, and let GitHub show any conflict.
  - For: no fetch, and fastest.
  - Against: a tasks-file conflict waits for the owner on GitHub, and the records check has not run on the merged result.

## Why

The owner chose it, it matches the earlier pull requests, and the one conflict could be checked here.

## Consequences

- **Done:** the merge is committed; the branch holds `origin/main` at `13ab255`.
- **Not done:** the push and the pull request (D7, waiting on task 37).
- **New task:** the engine thread warning in `test_a_task_whose_when_does_not_hold_is_skipped_and_the_stage_still_finishes`, which is in `docs/tasks.md` as item 39.
- **Task:** `docs/tasks.md` item 38 (the push) and the Log.

## Source

Written 2026-11-22 by the Claude Code session that applied the owner's answer (run `d5c2b949-b212-4992-9a5c-6284ed60de53`), from the page `.scratch/pilot-and-push.json`, decision `D3`.
