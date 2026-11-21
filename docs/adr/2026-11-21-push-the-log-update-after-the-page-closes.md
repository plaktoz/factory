---
scope: repo
repo: factory
topic: push-the-log-update-after-the-page-closes
status: accepted
supersedes: []
---

# The branch is pushed as one pull request once the open items page is closed

## Decision

Accepted by the owner on 2026-11-21, on the page "Open items after the issue 55 follow-ups" (`.scratch/open-owner-items.json`, since deleted; its answers are in these records), decision `D7`: option `push-after-answers`, the recommended option.

The branch `plaktoz/proposal-standardized-spec-adr-scoring-rubric-re` is pushed as one pull request after every card on the page is closed. Nothing is pushed before then.

## Context

The branch holds six commits that are not on `origin/main`, and it is 33 commits ahead of its own remote branch. Those six are the records and fixes for the answers on the page: `2b71a61`, `c197dc2` (D1), `0930e32` (D2), `ac3c9f5` (D3), `97992f4` (D5) and `6ac5188` (D6). The page's last card (D4) is still open, so the page is not closed.

Checked before deciding: PR #73 from this branch merged on 2026-11-21 (`0952192`), so a new PR from the same branch name would hold a history that is already partly merged. The branch was not pushed.

## Options considered

- **`push-after-answers`** (chosen, recommended): one pull request, pushed when the page is closed.
  - For: one review, and every answer is in it together.
  - Against: nothing is on GitHub until the page is closed.
- **`push-now`** (not chosen): push the first commit now, the answers in a second pull request.
  - For: the log is on GitHub at once.
  - Against: two pull requests, and the second touches the same file.
- **`keep-local`** (not chosen): push nothing until the owner says so.
  - For: no outward action.
  - Against: the records live only on this machine.

## Why

One pull request is easier to review than two for a tasks file, and the page's answers belong together.

## Consequences

- **Not done:** the push and the pull request. Both wait until D4 is closed and the page is removed.
- **Before pushing:** check that the branch merges cleanly with `origin/main` (it has moved since `7d6d051`). Do not fetch or merge `main` without asking, per `AGENTS.md`.
- **Task:** `docs/tasks.md` item 43.

## Source

Written 2026-11-21 by the Claude Code session that applied the owner's answer (run `d5c2b949-b212-4992-9a5c-6284ed60de53`), from the page `.scratch/open-owner-items.json`, decision `D7`.
