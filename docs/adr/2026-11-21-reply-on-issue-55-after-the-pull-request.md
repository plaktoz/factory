---
scope: repo
repo: factory
topic: reply-on-issue-55-after-the-pull-request
status: accepted
supersedes: []
---

# The reply on issue 55 waits for the pull request, and links it

## Decision

Accepted by the owner on 2026-11-21, on the follow-up page for issue 55 (`.scratch/issue-55-follow-ups.json`, since deleted; its answers are in these records), decision `D5`: option `reply-after-pr`, the recommended option. One comment on issue 55 was to link the pull request and list what changed from the proposal and why.

**Status of the comment: not posted.** Issue 55 closed at 11:51:30 UTC on 2026-11-21, two seconds after PR #73 merged at 11:51:28 UTC; the PR body says `Closes #55`. The issue had no comments when this record was written. The PR description names the dropped weights, the 4.0 bar and the 3.0 floor, and links the ADR that explains them.

## Context

Issue 55 proposed weights of 25, 30, 25 and 20, a 4.0 pass bar, a 3.0 floor per category and a skill named `review-spec`. The built skill is `revise-spec` and has no weights; the lowest score decides (`2026-11-21-scorecard-is-set-by-the-lowest-score`).

## Options considered

- **`reply-after-pr` (chosen, recommended).** Reply once the pull request exists, with its link.
  - For: the author sees the reasons and can open the change.
  - Against: public and hard to unsay.
- **`reply-now` (not chosen).** Reply before any pull request, with no link.
- **`no-reply` (not chosen).** Do not comment.

## Why

The author asked four questions in the issue, and a link lets them see each answer.

## Consequences

- The condition for the reply is met: the pull request exists and is merged. The issue is closed, so a comment now would go on a closed issue.
- Not built: the comment itself. Whether to post it on a closed issue is open.

## Source

Written on 2026-11-21 by Claude Code from the owner's answer on the follow-up page for issue 55 (`.scratch/issue-55-follow-ups.json`, since deleted; its answers are in these records), decision `D5`. The answer is the owner's, not new. The issue state and comment count are from `gh issue view 55`.
