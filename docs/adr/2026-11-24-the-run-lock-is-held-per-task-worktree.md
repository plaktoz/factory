---
scope: repo
repo: factory
topic: the-run-lock-is-held-per-task-worktree
status: proposed
supersedes: [2026-11-14-run-lock-is-an-os-file-lock]
---

# Should the run lock be held for each task worktree instead of each run?

## Decision

Question for the owner: the owner asked on 2026-11-24 for the run lock to be held per worktree while the factory runs, so tasks go on in parallel, with no shared lock for operations that touch the main repo, and `resume --force` taking over one task only. Which of the four designs below do you want?

Recommended: **option D, no lock change**: make `Engine.run` drive runs at the same time and make the `max_workers` cap real. It gives the parallelism without changing a shared contract. Option A (a lock for each task, plus a short lock held only while a state file is written) is built only if the owner still wants it after D.

If the owner accepts A: `Lock` in section 18 and module 6 gains a task field; `acquire_lock` and `lock_status` take it; the row `2026-11-14-run-lock-is-an-os-file-lock` is replaced.

## Context

Facts read or run on 2026-11-24 (`main` at `984e533`):

- The run lock is one OS file lock on `<factory home>/runs/<repo key>/<run id>/lock` (`lock.py`), taken once by `Engine._drive`, and for one pass by `tick`, `resume`, `stop`, `retry`, `goto`, `skip`, `api.recover`, intake and `housekeeping._archive`. It is not inside any worktree.
- Tasks of one run already run at the same time, up to `concurrency` (default 4): `Engine._execute_tasks` starts a task when its `needs` are done and a slot is free (test `test_a_task_starts_when_its_needs_are_done_while_a_slower_task_is_still_running`). Different runs have different lock files.
- `Engine.run` drives several runs one after another in one process. `max_workers` (default 6) is read by no code (`git grep max_workers`).
- `resume(force=True)` has no effect: it skips its own check, and `acquire_lock` then raises `state.locked` for a live holder (run on 2026-11-24).
- A lock file inside a worktree protects nothing: `shutil.rmtree` removed a folder holding a locked file with no error (macOS, 2026-11-24, `flock` is advisory). A lock file outside the folder was honoured by a second process.
- Twelve parallel `git worktree add` calls in a scratch repo, three rounds, gave 0 failures.
- `Lock` (path, fd, owner, pid) is a shared contract; 18 test files use `acquire_lock` or `lock_status`.

- What the run lock protects, and what each design keeps: (1) one engine at a time edits one task worktree (every design keeps it); (2) only the lock holder writes `run.json` and `task.json`, which sit in the run folder and not in a worktree (a lock per worktree alone loses it, which is why option B is weak); (3) a crash frees the lock at once and a stopped process keeps it (kept while the lock stays an OS file lock); (4) housekeeping and intake cannot touch a run an engine is driving (kept if a run counts as live when any task lock is held).
- What stays serial under every design: writes to `run.json` and `task.json`, the join of task branches onto the run branch, `git push`, and one `factory gc` at a time. `tick.lock` (one tick at a time on the machine) is not changed.
- Assumptions, not established: a "worktree" here means a task worktree and not the run worktree; "no shared lock for the main repo" means no repo-wide or machine-wide lock around `git` calls; the path `tasks/<id>/lock` is a proposal; Windows keeps `msvcrt` locking and was not tested; a rule for runs in flight when option A lands is Unspecified.

## Options considered

A. **A lock for each task, plus a short run-state lock.** Each task gets `tasks/<id>/lock` in the run folder; `<run dir>/lock` stays but is held only while `run.json`, `task.json` or `events.jsonl` is written. `lock_status` is `live` if any is held. For: a takeover of one stuck task without stopping the others. Against: changes a shared type and replaces a row; needs a migration for runs in flight; adds little over `concurrency`.
B. **A lock for each task only.** For: matches the request's wording. Against: two engines could write `run.json` at once, which breaks the rule that only the lock holder writes it.
C. **No lock; use git's own locks.** For: no new code. Against: nothing stops a second engine on a run; crash and SIGSTOP behaviour is lost.
D. **No lock change (recommended).** Drive runs concurrently in `Engine.run`, and enforce `max_workers`. For: removes the two real serial points; no contract change. Against: `resume --force` stays a no-op and should be removed from the spec (decision `resume-has-no-force`).

## Why

The premise that the run lock serialises tasks is not what the code does, so option D meets the stated goal at the least risk. Option A is still on offer because the owner asked for a per-task takeover.

## Consequences

- If D: `Engine.run` starts one engine for each run in parallel; `max_workers` becomes a real cap; module 3 line 80 and module 6 are updated; `force` leaves the `resume` signature.
- If A: section 18, module 6, module 16, the tick, `gc` and the dashboard read the new `lock_status`; a one-time rule for runs in flight; new tests for two held locks, a SIGKILL that frees one, and a SIGSTOP that keeps one.
- Not built by this ADR: any of it. The design in full is in `docs/tasks.md` item 56.
- Supersedes: `2026-11-14-run-lock-is-an-os-file-lock`, only if A or B is accepted.

## Source

Written 2026-11-24 from the owner's request in the session ("hold the lock per worktree"), the decision page "Decided at the recommendation, 2026-11-24", decision D1, and the proposal in `.scratch/backlog-2026-11-24/proposal-per-worktree-lock.md`. Its content is copied above, so the file is not needed to read it.
