# Spec workflow pilot: setup

The pilot tests the spec steps from [issue #56](https://github.com/plaktoz/factory/issues/56) by hand on two medium tickets. The factory's workflows do not change. The decisions behind it are three ADRs:

- [`2026-11-21-spec-workflow-applies-by-hand-first`](../adr/2026-11-21-spec-workflow-applies-by-hand-first.md): run it by hand first.
- [`2026-11-21-spec-rules-live-in-agents-md-and-issue-form`](../adr/2026-11-21-spec-rules-live-in-agents-md-and-issue-form.md): the rules are in `AGENTS.md`, and each ticket's spec is its GitHub issue.
- [`2026-11-21-adversarial-check-is-a-fresh-session-by-hand`](../adr/2026-11-21-adversarial-check-is-a-fresh-session-by-hand.md): a fresh session checks the diff before the pull request.

The ADRs leave steps 2 to 5 below undecided. Each of those steps has a default. Change a default in this file before the pilot starts, and record the change in task 18 of [`docs/tasks.md`](../tasks.md).

## Setup

1. **Merge the form and the rules.** The issue form is `.github/ISSUE_TEMPLATE/spec.yml`, and the rules are the "Specs and checks" section of `AGENTS.md`. GitHub shows an issue form only when it is on `main`, so merge the pull request that adds them first.
2. **Name one owner for the first draft of the rules.** Default: the repo owner. Write the name in task 18.
3. **Pick two medium tickets.** A medium ticket is larger than a chore, which is the line `AGENTS.md` draws. Choose tickets nobody has started, and write their issue numbers in task 18. Drive both by hand, not through a factory run: a GitHub issue gives a factory run an empty acceptance list.
4. **Pick the baseline.** Choose two merged tickets of similar size from before the pilot. For each one, record the time the pull request opened, the time of its first approval, the time it merged, and its defects.
5. **Define the measures before the pilot starts.** Do not change them after you see the numbers. Defaults:
   - **Review time:** the hours from the pull request opened to its first approval.
   - **Defect:** a bug issue or a revert traced to the ticket within 14 days of the merge.

## Run each pilot ticket

1. Open an issue from the "Spec" form. Fill in all four fields: Goal, Not included, Contracts and Acceptance.
2. Approve the spec in a comment on the issue before anyone writes code.
3. Build the ticket.
4. Start a fresh session. Give it the diff and the acceptance list, and nothing else. It reports each criterion as met, unmet or untested, with the line or test that shows it.
5. Open the pull request, and paste that report into its description.
6. Record the review time and any defects.

## Compare at day 14

1. Put the pilot numbers next to the baseline.
2. Count the fresh-session findings that were real problems and the findings that were noise.
3. Note each step a person skipped.
4. Choose the start day yourself. This file sets no dates.

## Decide

Write a new ADR with `supersedes: [2026-11-21-spec-workflow-applies-by-hand-first]`. It chooses one of three options: keep the rules as a house rule, build them into a factory workflow, or drop them. Then update tasks 18 to 20 in [`docs/tasks.md`](../tasks.md).

## Known limits

These come from the ADRs. Read them when you judge the numbers.

- A hurried ticket can skip the steps, because a habit enforces them and the factory does not.
- A chore run gets no check against its acceptance list.
- The spec lives in the issue, so an edit to it does not show in git history. The factory flags a body change while a run is active, but it does not stop the run.

## Fill in before the pilot starts

| Item | Value |
| --- | --- |
| Owner of the first draft | The repo owner (`plaktoz`) |
| Pilot ticket 1 | [#86](https://github.com/plaktoz/factory/issues/86): `factory gc` by real GitHub pull request state (task 34). Scratch repo: `plaktoz/factory-gc-scratch` (private) |
| Pilot ticket 2 | [#87](https://github.com/plaktoz/factory/issues/87): an engine crash stops a task after `max_interruptions` (module 8) |
| Baseline ticket 1 | [PR #74](https://github.com/plaktoz/factory/pull/74), see the baseline record below |
| Baseline ticket 2 | [PR #71](https://github.com/plaktoz/factory/pull/71), see the baseline record below |
| Start day | 2026-11-22. Day 14 is 2026-12-06 |

## Baseline record

Taken on 2026-11-22 from GitHub. Neither pull request links to an issue, so a defect cannot yet be traced to a ticket by its link. Defects are counted to 2026-12-05, the end of each 14-day window.

| Measure | PR #74 | PR #71 |
| --- | --- | --- |
| Title | Give the worker the real task folder path in its prompt | Stream Claude task logs, template research questions, check auto-merge at open and green |
| Size | +66 / -5, 6 files | +677 / -49, 33 files |
| Opened | 2026-11-21 11:39 UTC | 2026-11-21 08:06 UTC |
| First approval | none: no review, no comment | none: no review, no comment |
| Merged | 2026-11-21 11:44 UTC (4 min 22 s after opening) | 2026-11-21 10:57 UTC (2 h 51 min after opening) |
| Defects, checked 2026-11-22 00:27 UTC+8 | none found: no revert PR, no bug issue | none found: no revert PR, no bug issue |
| Defect window ends | 2026-12-05 | 2026-12-05 |

**Not similar in size.** The pilot's own rule asks for baseline tickets of similar size. PR #71 is about ten times PR #74 by changed lines, and it bundles four separate changes. Review time is also undefined for both: neither has an approval, so the measure "hours from opened to first approval" has no value to compare. Both were merged by the author without review.

