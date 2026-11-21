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
| Owner of the first draft | not named |
| Pilot ticket 1 | not named |
| Pilot ticket 2 | not named |
| Baseline ticket 1 | not named |
| Baseline ticket 2 | not named |
| Start day | not set |
