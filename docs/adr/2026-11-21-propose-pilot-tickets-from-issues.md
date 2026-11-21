---
scope: repo
repo: factory
topic: propose-pilot-tickets-from-issues
status: accepted
supersedes: []
---

# The pilot's tickets and start day are proposed from the issue list, for the owner to confirm

## Decision

Accepted by the owner on 2026-11-21, on the page "Open items after the issue 55 follow-ups" (`.scratch/open-owner-items.json`, since deleted; its answers are in these records), decision `D4`: option `propose-from-issues`. The owner chose it over the recommended option, `i-will-name-them`.

The owner's choice is that the session proposes the pilot tickets and start day from the open issues and recent merged pull requests, and the owner confirms them. The table in `docs/setup/spec-workflow-pilot.md` is not filled in until the owner confirms.

## Context

The pilot table has five rows still at "not named" or "not set": the first-draft owner, two pilot tickets, two baseline tickets, and the start day.

Checked by running `gh` on 2026-11-21:

- **Open issues: one.** #56, "Industry Evaluation (Top 3 SDD Frameworks)", is the research behind the pilot, not a ticket to build. #55 is closed. So no open medium ticket exists to propose as a pilot ticket.
- **Baseline candidates exist, but cannot measure the pilot's review-time measure.** The pilot defines review time as the hours from a PR opened to its first approval. Of the 60 most recent merged PRs, only #43 has any review or comment, and it has a comment and no approval. The merged PRs #57 and #61 were each opened and merged within one minute, with no review. Any baseline from these PRs would have no review-time value.
- **Two merged PRs, as examples of the shape of work:** #68 (+64/-2, merged 2026-11-21) and #74 (+66/-5, merged 2026-11-21).

So the proposal the owner asked for cannot name two pilot tickets. The pilot needs either tickets the owner names, or new issues that the owner creates.

## Options considered

- **`propose-from-issues`** (chosen by the owner): the session proposes from the issue list, and the owner confirms.
  - For: the owner does not need to look up the numbers.
  - Against: the issue list has no open medium ticket today, so the proposal is blocked until the owner names tickets or creates issues.
- **`i-will-name-them`** (the recommended option, not chosen): the owner writes the four issue numbers and the date.
  - For: the owner knows which tickets are medium and untouched.
  - Against: the owner has to look the numbers up.
- **`postpone-pilot`** (not chosen): leave the table as "not named" and say the pilot is on hold.
  - For: no commitment now.
  - Against: the agent instructions stay untested, and the decision about keeping them has no date.

## Why

The owner chose to have the session propose the tickets. That is recorded. The proposal itself cannot be made until the issue list has a medium ticket in it, so the task waits on the owner for that.

## Consequences

- **Not done:** the pilot table, the two pilot tickets, the two baseline tickets, and the start day. The task waits on the owner.
- **Measure gap:** the review-time measure has no baseline in this repo, because merged PRs have no approvals. The owner should decide how the baseline review time is measured, or accept an empty baseline and say so.
- **Task:** `docs/tasks.md` item 42.

## Source

Written 2026-11-21 by the Claude Code session that applied the owner's answer (run `d5c2b949-b212-4992-9a5c-6284ed60de53`), from the page `.scratch/open-owner-items.json`, decision `D4`.
