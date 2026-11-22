# Spec workflow pilot: setup

The pilot tests the spec steps from [issue #56](https://github.com/plaktoz/factory/issues/56) by hand on two medium tickets. The factory's workflows do not change. The decisions behind it are three ADRs:

- `2026-11-21-spec-workflow-applies-by-hand-first` (row in `docs/process.md`): run it by hand first.
- `2026-11-21-spec-rules-live-in-agents-md-and-issue-form` (row in `docs/process.md`): the rules are in `AGENTS.md`, and each ticket's spec is its GitHub issue.
- `2026-11-21-adversarial-check-is-a-fresh-session-by-hand` (row in `docs/process.md`): a fresh session checks the diff before the pull request.

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
| Pilot ticket 1 | [#86](https://github.com/plaktoz/factory/issues/86): `factory gc` frees worktrees by real GitHub pull request state (PR #96) |
| Pilot ticket 2 | [#87](https://github.com/plaktoz/factory/issues/87): an engine crash stops a task after `max_interruptions` (PR #99) |
| Baseline ticket 1 | [PR #74](https://github.com/plaktoz/factory/pull/74), see the baseline record below |
| Baseline ticket 2 | [PR #71](https://github.com/plaktoz/factory/pull/71), see the baseline record below |
| Start day | 2026-11-22. Day 14 is 2026-12-06 |

Issues #88 and #89 were opened on 2026-11-22 as candidate tickets (task 42). The pilot did not use them. Both are still open spec issues.

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

**Review time, as changed on 2026-11-22** (owner decision D2, ADR `2026-11-22-measure-review-time-as-open-to-merge.md`): the measure is now minutes from opening to merging, which has a value for both: #74 4.4 min, #71 171.4 min. The first-approval measure above is no longer used.

## Pilot record

Taken on 2026-11-22 from GitHub and the two pull requests' descriptions.

| Measure | PR #96 (#86) | PR #99 (#87) |
| --- | --- | --- |
| Size | +146 / -4, 5 files | +190 / -8, 8 files |
| Opened to merged (review time, D2) | 0.4 min (00:22:01 to 00:22:26 UTC) | 0.9 min (05:10:43 to 05:11:37 UTC) |
| First approval | none: no review, no comment | none: no review, no comment |
| Spec approval | none on the issue: the owner approved in chat, and #86 has only a closing comment | none on the issue: the owner approved in chat, and #87 has no comments |
| Issue closed | by hand, 05:19 UTC, because the PR had no `Closes #86` | by the PR, `Closes #87` |
| Defects, window ends 2026-12-06 | pending | pending |

**Fresh-session findings** (the report in each PR, sorted by whether the finding was real):

- **PR #96, two sessions.** Real and fixed: a task 34 paraphrase that contradicted its older text (`e8912db`), and a `--apply` output pasted as prose instead of raw JSON (`41b5f14`). Real and open: the empty `detail` case is untested. Noise or judgment, not changed: the wording of criterion 3b ("removes nothing" holds for worktrees only), the stub's `gh` error text, the test's `sys.path` import, and the absence of commit evidence on the issue's boxes.
- **PR #99, one session.** Real and open: the test for the `high` half of the two-task case would pass even if the loop never evaluated `high`; the status test does not check that the output names the task or the reason. Judgment, not changed: the resume-time `config.invalid` when a workflow is edited after a crash is a design choice, recorded in the PR. Noise: the negative and non-integer refusal is the schema's job, and the test for it passes as intended.

Count: PR #96 had 2 real findings, both fixed, and 1 real gap open. PR #99 had 2 real findings, both open. Judgment or noise, not changed: 4 on PR #96, 2 on PR #99.

**Steps skipped or changed:**

- Step 2 of "Run each pilot ticket" (approve the spec in a comment on the issue) was done in chat for both tickets. The issues carry no approval comment.
- Both pilot PRs were merged by their author, with no review, 25 s and 54 s after opening. The baselines had no review either. Their open-to-merge times were 4.4 and 171.4 minutes, so the pilot's speed is not a like-for-like comparison.
- The pilot table named #88 and #89 until this fix, while task 18 named #86 and #87.

