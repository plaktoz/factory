---
scope: repo
repo: factory
topic: measure-the-spec-pilot-on-existing-history
status: proposed
supersedes:
  - 2026-11-21-spec-workflow-applies-by-hand-first
  - 2026-11-22-measure-review-time-as-open-to-merge
---

# Measure the spec pilot on existing history, with a script, instead of waiting for day 14

## Proposal

The spec pilot is measured by `scripts/spec-pilot.py`. The script can run at any time. Its window ends at the moment it runs, and it uses only history that already exists. The fixed day 14 comparison on 2026-12-06 is dropped.

- **Spec group.** A pull request that closes a `[Spec]` issue, or names one in its title. Today that is PR #96 (#86), PR #99 (#87) and PR #106 (#103).
- **Baseline group.** Every other pull request merged to `main` that adds code under `factory/`.
- **Equal follow-up.** Each pull request is followed for the same H hours from its merge. A pull request merged less than H hours ago is listed as too recent. It is left out, and never counted as zero.
- **Defect signal: rework.** Rework is the share of a pull request's added lines under `factory/` that are gone or rewritten H hours after its merge (`git blame` at the merge against `git blame` at the window's end). Bug-labelled issues and reverts are counted too.
- **Decision rule, fixed before the run.** The result is inconclusive when more than half of the baseline group shows no rework, because a spec rate of 0 is then what both groups would show. Otherwise, a spec rate outside the baseline range is a difference, and a rate inside the range is no evidence either way.

The rules themselves, the `AGENTS.md` table and the issue form, stay in force while the measure is inconclusive.

## Context

The pilot ADR set a 14-day defect window from each merge, so the earliest result was 2026-12-06. The owner asked for a result that can be checked now: start earlier and end today.

Measured on 2026-11-22 at about 13:25 UTC, on `origin/main` at `b9cd27d`:

- The repo's first commit is on 2026-11-14. The spec rules started on 2026-11-21 (PR #72, merged 11:47 UTC). No spec pull request can predate that.
- The spec pull requests merged 13.0 h, 8.2 h and 2.0 h before the run.
- Rework needs a long window to show anything. The share of baseline pull requests with no rework was 0.53 at 24 h (45 pull requests), 0.47 at 72 h (34), and 0.36 at 168 h (25). At 1.9 h it was 47 of 53 (0.89), and at 8 h it was 0.72 across 50 pull requests.
- At 1.9 h, the longest window that covers all three spec pull requests, all three show a rate of 0.00 or 0.01. That is inside the baseline range, and the window has no power: 47 of 53 baselines show 0 too.
- A backward score was tried: mark old pull requests that would have met the rules, and compare their rework. None of the 34 pull requests with a 72 h window has an acceptance list or a "not included" section in its body, so there is no group to compare.
- No bug-labelled issue and no revert exist on `main`.

The script's tests are in `scripts/test_spec_pilot.py` (6 passed). They cover a throwaway repo with a planted rewrite (4 lines added, 1 rewritten later: it reports 4 and 1), an untouched pull request (0 reworked), four planted summaries (mostly zero, inside, outside, no spec rows), and the grouping rule. Disabling the zero-share guard makes one of them fail.

## Options considered

- **`script-now`** (recommended): measure with the script on existing history, at any time, and record its verdict as it stands.
  - For: a result exists today, and anyone can rerun it.
  - For: an inconclusive result says so, with the reason. It is never a zero.
  - For: no date to wait for. The next run on a later day uses a longer window with no change to the method.
  - Against: rework is a proxy. A line can change for a reason that is not a defect, such as a planned follow-up.
  - Against: on 2026-11-22 the verdict is inconclusive. A useful window, about 72 h or more, is first possible on 2026-11-25 for PR #96.
- **`day-14`** (not chosen): keep the 14-day defect count and the comparison on 2026-12-06.
  - For: no change to an accepted decision.
  - Against: no result before 2026-12-06, and the measure (one bug issue or one revert) has never fired on this repo, so it is likely to read 0 for both groups.
- **`backfill`** (not chosen): score old pull requests by whether they would have met the rules.
  - For: it would use the whole history.
  - Against: measured, no old pull request has an acceptance list or a "not included" section, so the group is empty.

## Decision needed from the owner

The data cannot decide whether the rules pay off. Choose one:

- **Keep the rules as a house rule** (the default if no answer): they stay in `AGENTS.md` and the issue form. Rerun the script after 2026-11-25 11:24 UTC with `--hours 72`.
- **Build them into a workflow**: reopens the phase 1 scope (the feature workflow is phase 1b).
- **Drop them**: remove the `AGENTS.md` rows and the issue form.

## Consequences

- **Changes now:** `scripts/spec-pilot.py`; this ADR; task 18 in `docs/tasks.md`; the pilot page `docs/setup/spec-workflow-pilot.md` points to the script. No factory code changes.
- **On acceptance:** the `Decisions` rows in `docs/process.md` for `2026-11-21-spec-workflow-applies-by-hand-first` and `2026-11-22-measure-review-time-as-open-to-merge` are replaced by one row for this rule, and this file is deleted.
- **Review time** (minutes from opening to merge) is dropped as a measure. All five pull requests in the pilot and baseline were merged by their author with no review, so it measured nothing about review.
- **What gets harder:** there is still no verdict today. The earliest run that can separate the groups is on 2026-11-25 after 11:24 UTC, when all three spec pull requests have a 72 h window. Task 18 stays open until a run gives a verdict, and the owner decides on keep, build or drop. Each later spec pull request also waits 72 h before it counts.
- **Replaced:** the day 14 count on 2026-12-06 and the session-only reminder scheduled for 2026-12-07 are no longer needed.
- **Not settled here:** whether rework is a good enough proxy. If a later run shows a difference, read the reworked lines before acting on it.

## Source

Written 2026-11-22 by the Claude Code session `1b7738e1-f437-433c-8de1-9308c798f467`, on the owner's request to verify issue #56 now rather than on the due date. Numbers from `python3 -I scripts/spec-pilot.py --hours <H> --json` on `origin/main` at `b9cd27d`.
