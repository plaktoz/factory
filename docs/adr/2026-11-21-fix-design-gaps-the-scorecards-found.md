---
scope: repo
repo: factory
topic: fix-design-gaps-the-scorecards-found
status: accepted
supersedes: []
---

# Every gap the scorecards found in modules 5, 14 and 17 is fixed in the spec now

## Decision

Accepted by the owner on 2026-11-21, on the follow-up page for issue 55 (`.scratch/issue-55-follow-ups.json`, since deleted; its answers are in these records), decision `D2`: option `fix-everything-now`. This is not the page's recommended option (`copy-from-code-now-tasks-for-rest`). The owner chose it, so the open design questions in the three files were answered in the spec and no gap was left as a task.

The edits are in `docs/design/modules/05-workflows-and-plugins.md`, `14-token-tracking.md` and `17-housekeeping.md`, in commit `6a69067` (PR #73).

## Context

The calibration (`2026-11-21-calibrate-revise-spec-on-real-files`) scored modules 5, 14 and 17 `needs-changes`. Some gaps copied what the code already did, such as the `GcPlan` and `GcReport` fields. Others were open design questions: how a still-open pull request is treated, whether a multi-model attempt splits its tokens, and what a failed `started` write does.

## Options considered

- **`fix-everything-now` (chosen).** Close every gap, including the open design questions.
  - For: one round of review, and the fastest route to files that no longer disagree with themselves or the code.
  - Against: design choices are made for the owner, the diff is large, and the files are tuned to the scorer.
- **`copy-from-code-now-tasks-for-rest` (not chosen, recommended on the page).** Fix only what the code settles; list the open questions as tasks.
- **`tasks-only` (not chosen).** Change no spec file; record each gap as a task.

## Why

The page listed one round of review, and an answer for each open question, as the benefit of this option. The owner chose it. Each design choice is written where a reader of the module will find it, and four of them have their own record (see the Consequences).

## Consequences

- The three files carry sections named "Choices made where this file was silent", so a reader can tell a choice from a rule that was always there.
- Four of those choices are recorded on their own: the unpushed-commit rule (`2026-11-21-gc-keeps-a-branch-that-has-unpushed-commits`), the PR hold (`2026-11-21-gc-keeps-a-worktree-while-its-pull-request-is-open`), the double count (`2026-11-21-keep-the-multi-model-double-count-and-label-it`) and the nine module 5 choices (`2026-11-21-keep-the-nine-module-5-choices`).
- Not shown by this record: that the three files now score `ready`. They were not re-scored; that is task 33.

## Source

Written on 2026-11-21 by Claude Code from the owner's answer on the follow-up page for issue 55 (`.scratch/issue-55-follow-ups.json`, since deleted; its answers are in these records), decision `D2`, as the session handoff of 2026-11-21 recorded it. The answer is the owner's, not new.
