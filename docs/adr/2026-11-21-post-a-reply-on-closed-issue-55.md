---
scope: repo
repo: factory
topic: post-a-reply-on-closed-issue-55
status: accepted
supersedes: []
---

# A reply is posted on closed issue 55

## Decision

Accepted by the owner on 2026-11-21, on the page "Open items after the issue 55 follow-ups" (`.scratch/open-owner-items.json`, since deleted; its answers are in these records), decision `D6`: option `post-reply`, the recommended option.

A comment was posted on `plaktoz/factory#55` from the owner's GitHub account: <https://github.com/plaktoz/factory/issues/55#issuecomment-7065249888>. It says the proposal was built as the advisory `revise-spec` skill and not a gate, points to PR #73, the ADRs dated 2026-11-21 and tasks 25 to 34, and gives the two calibration findings.

## Context

Issue 55 proposed a weighted scoring rubric for specs and ADRs. It closed itself two seconds after PR #73 merged and had 0 comments, so the change from a gate to an advisory skill was written only in the repo's records (`2026-11-21-push-the-branch-and-open-a-pull-request` records that no reply had been posted).

Checked before posting, by running `gh`: PR #73 is "Add the revise-spec skill and fix the gaps its calibration found", merged 2026-11-21; `.claude/skills/revise-spec/` holds `SKILL.md`, `references/` and `scripts/`; the ADRs the reply names exist. After posting, `gh issue view 55` shows 1 comment of 510 characters.

The two calibration claims in the reply are the ones in `.claude/skills/revise-spec/references/calibration-2026-11-21.md`: no design file reached `ready`, and the strong ADR was `ready` on 1 run of 5.

## Options considered

- **`post-reply`** (chosen, recommended): post a short comment.
  - For: anyone who finds the issue learns the outcome without reading the repo.
  - Against: it is public and written under the owner's name, and watchers of the issue get a notification. It can be edited or deleted afterwards, but a notification cannot be taken back.
- **`no-reply`** (not chosen): post nothing.
  - For: no public action, and the outcome is already in the repo's records.
  - Against: the issue reads as if nothing was built.

## Why

A short comment saves the next reader a search, and the repo is the owner's.

## Consequences

- **Done:** the comment is posted. Nothing else changes in the repo.
- **If the wording is wrong:** edit or delete the comment on GitHub. The comment says "tasks 25 to 34"; `docs/tasks.md` now also has items 35 and later, which are not part of issue 55.
- **Task:** `docs/tasks.md` item 36.

## Source

Written 2026-11-21 by the Claude Code session that applied the owner's answer (run `d5c2b949-b212-4992-9a5c-6284ed60de53`), from the page `.scratch/open-owner-items.json`, decision `D6`.
