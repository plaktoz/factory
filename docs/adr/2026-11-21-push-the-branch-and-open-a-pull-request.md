---
scope: repo
repo: factory
topic: push-the-branch-and-open-a-pull-request
status: accepted
supersedes: []
---

# The revise-spec branch is pushed and opened as a pull request

## Decision

Accepted by the owner on 2026-11-21, on the follow-up page for issue 55 (`.scratch/issue-55-follow-ups.json`, since deleted; its answers are in these records), decision `D4`: option `push-and-open-pr`, the recommended option.

The branch `plaktoz/proposal-standardized-spec-adr-scoring-rubric-re` was pushed and opened as PR #73 against `main`. It was merged on 2026-11-21 at 11:51 UTC as `0952192`; the record does not say who clicked merge.

## Context

The branch had no remote copy and no upstream. Earlier work reached `main` through pull requests (62 to 64), and a pushed branch is the only backup of the work.

## Options considered

- **`push-and-open-pr` (chosen, recommended).** One push, one pull request into `main`.
  - For: the work is backed up and reviewed in one place.
  - Against: the records are public to anyone who can see the repo, and the merge adds an `AGENTS.md` rule that every agent follows.
- **`push-draft` (not chosen).** The same push, as a draft.
- **`keep-local` (not chosen).** No push.

## Why

A pushed branch is the only backup, and the pull request is how earlier work reached `main`.

## Consequences

- The `AGENTS.md` rule to run `revise-spec` before marking a design change done is on `main`.
- The PR needed two merges of `main` before it was mergeable, because `main` had its own items 18 to 24 in `docs/tasks.md`. The revise-spec items were renumbered from 18 to 27 to 25 to 34.
- Not checked before the merge: the full engine suite on the merged tree. That run was stopped when `main` moved again.

## Source

Written on 2026-11-21 by Claude Code from the owner's answer on the follow-up page for issue 55 (`.scratch/issue-55-follow-ups.json`, since deleted; its answers are in these records), decision `D4`. The answer is the owner's, not new. The PR number, merge commit and time are from `gh pr view 73`.
