---
scope: repo
repo: factory
topic: repo-supplies-worktree-comparison
status: accepted
supersedes: []
---

# Where the repo's worktree comparison comes from

## Decision

the repo supplies the comparison as a command and sets `cleanup_check`; the spec stays as written

Chosen option: `repo-script`.

## Context

The pilot repo's rule is to compare each changed file with the committed or merged file before a forced removal. It has no script that does this. With `cleanup_check` unset, every worktree that is not clean is skipped and reported, so they pile up until someone clears them. Untracked and ignored files have no committed copy to compare with.

## Options considered

- **`repo-script`** (chosen) (recommended): The repo supplies the comparison as a command and sets `cleanup_check`; the spec stays as written
  - For: The rule lives with the repo that owns it
  - For: No engine code that guesses what the rule means
  - For: Other repos with other rules use the same key
  - Against: The pilot skips every worktree that is not clean until it adds the script
  - Against: Needs a change in the pilot repo, which you own
- **`builtin-compare`**: The factory ships a built-in comparison that checks changed tracked files against the run branch
  - For: Works in the pilot at once
  - For: One implementation shared by every repo
  - Against: The engine decides what 'safe to remove' means, which is the repo's rule to set
  - Against: It can only report untracked and ignored files, not judge them
- **`never-force`**: No check at all: a worktree that is not clean is always kept, and you clear it by hand with `factory gc`
  - For: Nothing is removed that was not compared by a person
  - For: No new key or code
  - Against: Drops the P2 decision you already took
  - Against: Leftover worktrees and branches grow with every dirty run

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

P2 made the repo's comparison the gate, so the repo should provide it.

## Source

Backfilled on 2026-11-16 from `docs/reviews/open-decisions.md`, decision `R3`, page `docs/reviews/open-decisions.json`. The owner chose this on 2026-11-14; the answer is the record's, not new.
