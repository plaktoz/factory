---
scope: repo
repo: factory
topic: measure-review-time-as-open-to-merge
status: accepted
supersedes: []
---

# Review time in the spec pilot is the time from opening to merging

## Decision

Accepted by the owner on 2026-11-22, on the page "Pilot start and the push" (`.scratch/pilot-and-push.json`, since deleted; its answers are in these records), decision `D2`: option `open-to-merge`, the recommended option. Review time is the minutes from a pull request's opening to its merge, for the two baseline pull requests and for each pilot ticket alike.

This replaces the default in `docs/setup/spec-workflow-pilot.md` step 5 ("the hours from the pull request opened to its first approval"), which is not used.

## Context

The default needs an approval. Checked on 2026-11-22 with `gh pr view`: neither baseline pull request has a review or a comment.

- #74: opened 2026-11-21 11:39:53 UTC, merged 11:44:15 UTC, reviews 0, comments 0. Open to merge: 4.4 minutes.
- #71: opened 2026-11-21 08:06:31 UTC, merged 10:57:54 UTC, reviews 0, comments 0. Open to merge: 171.4 minutes.

So "first approval" has no value for either baseline, and the baseline record in the pilot doc already says so. The repo has one collaborator, `plaktoz`, and every merged pull request in the last 15 was written and merged by that account, so an approval from another person does not happen in this repo today.

## Options considered

- **`open-to-merge`** (chosen, recommended): minutes from opening to merging.
  - For: it has a value for both baselines and will for each pilot ticket, and it needs no new habit.
  - Against: it includes time spent fixing, not only reviewing, and because the owner merges their own work it shows the owner's pace more than a reviewer's.
- **`fresh-session-minutes`** (not chosen): time the fresh-session check, from the diff handed over to its report.
  - For: it measures the step the pilot adds.
  - Against: no baseline exists, because the earlier pull requests never had that step. It would be two pilot tickets with nothing to compare.
- **`defects-only`** (not chosen): drop the time measure and judge the pilot on defects within 14 days.
  - For: nothing to estimate, and both baselines have a defect count of 0.
  - Against: with two tickets and a baseline of 0, one bug is the only signal, and the measure says nothing about review cost.

## Why

It is the only time measure that has a value for both baselines, so the day 14 comparison in the pilot doc can be made.

## Consequences

- **Measure changed before the pilot's first ticket.** The pilot doc says measures are fixed before the pilot starts; this is recorded here and in task 18, before any pilot ticket is opened.
- **The defect measure stays** as the pilot doc defines it: a bug issue or a revert traced to the ticket within 14 days of the merge.
- **Not built:** nothing in the factory. This is a measure for a by-hand pilot.
- **Limit:** the measure cannot separate review from fixing time, and the owner merges their own work. The day 14 note must say so next to the numbers.
- **Task:** `docs/tasks.md` item 37 (the pilot setup) and the Log.

## Source

Written 2026-11-22 by the Claude Code session that applied the owner's answer (run `d5c2b949-b212-4992-9a5c-6284ed60de53`), from the page `.scratch/pilot-and-push.json`, decision `D2`.
