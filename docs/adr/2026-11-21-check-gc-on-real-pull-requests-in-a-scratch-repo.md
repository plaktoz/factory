---
scope: repo
repo: factory
topic: check-gc-on-real-pull-requests-in-a-scratch-repo
status: accepted
supersedes: []
---

# The worktree cleanup is checked on real pull requests in a scratch repo

## Decision

Accepted by the owner on 2026-11-21, on the page "Open items after the issue 55 follow-ups" (`.scratch/open-owner-items.json`, since deleted; its answers are in these records), decision `D2`: option `new-scratch-repo`, the recommended option.

The check was run on a new private repo, `plaktoz/factory-gc-scratch`, with one open, one merged and one closed pull request. The result matched the expected one (below). The repo is archived, not deleted: the token the session uses has no `delete_repo` scope. Deleting it is an owner action (see Consequences).

## Context

Task 34 asked for `factory gc` to be run against real GitHub pull request state. Until now, `api.gc` had only been tested with `FakePullRequests`.

What was run, on 2026-11-21:

- The scratch repo has three pull requests, each from its own branch with one small file: `#1 pr-open` (OPEN), `#2 pr-merged` (MERGED, squash), `#3 pr-closed` (CLOSED, not merged). Created with `gh repo create --private`, `gh pr create`, `gh pr merge` and `gh pr close`.
- A run folder was made for each branch in a temporary `FACTORY_HOME`, with its worktree on that branch, a `done` status, an end time 10 days ago (older than `archive_after_days`, 7), and a `pr` record with the real pull request number and URL.
- `api.gc(repo)` planned the cleanup with the default pull request client (`default_prs`, which calls `gh pr view` in the repo), then `api.gc(repo, apply=True)` carried it out.

Result, with the real client:

```
--- plan
remove   closed (run run-closed)
remove   merged (run run-merged)
keep     open - pull request open - https://github.com/plaktoz/factory-gc-scratch/pull/1
--- after apply
worktrees left: ['open']
```

Control, the same runs with the pull request client left out (`prs=None`, the state before `api.gc` passed `default_prs`):

```
keep     closed - pull request cannot be read - gc was given no pull request service; the worktree and its branch are kept
keep     merged - pull request cannot be read - gc was given no pull request service; the worktree and its branch are kept
keep     open - pull request cannot be read - gc was given no pull request service; the worktree and its branch are kept
worktrees left: ['closed', 'merged', 'open']
```

So the fix is what changes the result, and the real client reads all three states correctly.

Limits of the check:

- It called `api.gc`, which is the function the `factory gc` command calls (`cli.py`, `_gc`). The `factory` command is not on this machine's PATH, so the command line itself was not run.
- The factory home used was a temporary folder. The real `~/.factory` was checked afterwards and holds nothing from these runs.
- The check ran against this repo's `factory.yaml` with no `cleanup_check` set. A dirty worktree was not part of the check.

## Options considered

- **`new-scratch-repo`** (chosen, recommended): a new throwaway private repo, with three pull requests, then the cleanup run.
  - For: nothing real is touched, and the same repo can serve the tutorial's fix-an-issue part.
  - Against: creating and deleting a repo is a visible action on the owner's account. The delete step needs a scope the token does not have, so the repo is archived for now.
- **`use-factory-repo`** (not chosen): three test pull requests in `plaktoz/factory`, then closed.
  - For: no new repo, and it matches real use.
  - Against: test pull requests stay in the history, and a slip could touch a real branch.
- **`skip-real-check`** (not chosen): keep the fake-only tests and leave task 34 open.
  - For: no GitHub activity.
  - Against: a wrong guess about real pull request state would show up only on the first real cleanup.

## Why

The check runs the real pull request client on pull requests that can be thrown away, and the control shows the difference the fix makes. It answers the question task 34 asked without touching a repo the owner keeps.

## Consequences

- **Task 34 is done.** Its evidence is in `docs/tasks.md`.
- **Not built:** `factory gc` as a command has not been run against real state; the check ran the function the command calls. The tick's pull request poll (item 16) still uses fakes for its own check; it is a separate gap.
- **Owner action:** delete `plaktoz/factory-gc-scratch` in the GitHub settings, or grant `delete_repo` (`gh auth refresh -h github.com -s delete_repo`) and delete it with `gh repo delete`. Until then the archived repo remains.
- **Task:** `docs/tasks.md` item 34.

## Source

Written 2026-11-21 by the Claude Code session that applied the owner's answer (run `d5c2b949-b212-4992-9a5c-6284ed60de53`), from the page `.scratch/open-owner-items.json`, decision `D2`.
