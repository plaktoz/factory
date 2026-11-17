---
scope: repo
repo: factory
topic: keep-history-with-work-email
status: accepted
supersedes: []
---

# Your work email in commit 6a6ff04

## Decision

Keep the history as it is. The text copy in docs/tasks.md is already removed. No force push

Chosen option: `keep-history-redact-text`.

## Context

Commit 6a6ff04 has your work email as its author, and the public GitHub API returns it for that commit. 44 of the 45 pull request heads on GitHub contain the commit, and 73 commits sit after it on main (77 in all). No fork exists. docs/tasks.md also holds the address as text; that text is removed in this same change, with no force push. New commits carry no email at all: 55 commits on main have an empty author email, and this repo's git config sets none. Removing the commit itself needs a force push of main, which you have not approved. GitHub's own guide says a rewrite does not clear its pull request refs, and only GitHub Support can.

## Options considered

- **`keep-history-redact-text`** (chosen) (recommended): Keep the history as it is. The text copy in docs/tasks.md is already removed. No force push
  - For: Matches your earlier choice B on authorship: keep current authors, no history rewrite
  - For: No SHA changes, so the 45 remote branches, the 21 local worktrees and open PR #43 stay valid
  - For: Reversible: you can still choose a rewrite later
  - Against: The address stays readable on that one commit through the GitHub API and git log, and in every clone made so far
  - Against: A rewrite gets dearer as history grows: it already touches 73 commits, and GitHub Support is still needed for the PR refs
  - Against: If the address is a risk to you, this option does nothing for it
- **`rewrite-and-support`**: Rewrite the history to replace the email, force-push every branch, then ask GitHub Support to purge the pull request refs
  - For: The only way to remove the address from this repository for good
  - For: Done now, it touches 73 commits, not more
  - Against: Needs your approval for force pushes, and breaks the standing rule not to force push
  - Against: Every commit after 6a6ff04 gets a new SHA: 73 on main, plus the 45 remote branches and open PR #43, which the other sessions must rebase
  - Against: The PR refs keep the old commit until GitHub Support acts, and a PR body can keep the address even then (GitHub's guide)
  - Against: git-filter-repo is not installed on this machine, so a tool must be added first
- **`new-repository`**: Start a clean repository from a squashed copy of main, then delete or make private the old one
  - For: No Support request and no force push: the new history never held the address
  - For: Zero forks and zero stars today, so nobody else depends on the old repository
  - Against: Loses the 45 pull requests, their review comments and the per-commit history the decision logs cite
  - Against: Open PR #43 and every other session's branch must be moved by hand, and the repository URL changes
  - Against: The address is gone only if the old repository is deleted or made private, which is your call and not reversible once deleted

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

You already chose to keep current authors, the text copy is gone, and a rewrite can still be done later; the cost of waiting is that the address stays on one commit.

## Source

Backfilled on 2026-11-16 from `docs/reviews/wave3-open-decisions.md`, decision `D1`, page `docs/reviews/wave3-open-decisions.json`. The owner chose this on 2026-11-15; the answer is the record's, not new.
