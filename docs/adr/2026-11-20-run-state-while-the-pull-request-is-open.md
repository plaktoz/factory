---
scope: repo
repo: factory
topic: run-state-while-the-pull-request-is-open
status: accepted
supersedes: []
---

# What state a run is in while its pull request is open

## Decision

Accepted by the owner on 2026-11-20, on page `docs/decision-pages/run-state-while-pr-open.json`, decision `D1`: option `merge-review-stop`.

After a run opens its pull request, it waits as `awaiting_approval` at a merge review. It ends `done` only when GitHub merges the pull request. A closed pull request aborts the run. Red CI sends the run back through the last stage's `on_fail` edge, with the failing check output as feedback, and the run opens no second pull request: it pushes the fix to the open one.

`tick` reads each waiting run's pull request with `watch_pr`. It writes no run state. It starts an engine only when the pull request is merged, closed or red, and that engine ends or routes the run.

## Context

Module 6 says delivery "opens the pull request or writes the sink. The run ends `done`, `failed` or `aborted`" (lifecycle step 5). It also says `tick` checks the pull requests of runs waiting on merge: merged finishes the run, closed aborts it, red CI routes it back to fix (step 3). Module 6's status table has a row, `awaiting_approval, merge review`, which the tick should check. Module 11 lists "Merge review" as a human stop answered on GitHub.

The code does not match either. `Engine._finish` (`engine.py`) calls `delivery.write_sink`, which opens the pull request, and then sets `run.status = "done"` in the same pass. Nothing holds the run open, so there is no waiting state for `tick` to poll. `tick.decide` returns nothing for `awaiting_approval` unless a decision is answered, so the merge-review row has no action. `delivery.watch_pr` has no caller outside tests.

Two related calls are also missing. `delivery.evaluate_merge` and `delivery.merge_or_request_review` have no caller outside tests, so the auto-merge decision (module 13) never runs on a live run. Whichever option is chosen must say where those calls go.

Constraints from the spec and AGENTS.md:

- Only the process holding a run's lock writes `run.json`. A tick may append events under its short lock (interface check 12), but it may not change a run's status.
- A terminal status (`done`, `failed`, `aborted`) is a housekeeping candidate. Module 6 says `done` means finished.
- A run with an open pull request is not finished. It still has to take red-CI fixes.

## Options

- **`merge-review-stop`** (recommended). After the pull request opens, `_finish` sets the run to `awaiting_approval` at a merge-review stop, with a `merge_review` attention item. It calls `evaluate_merge`, then `merge_or_request_review`, so auto-merge and human review both start there. `tick` reads `watch_pr` for each such run, appends `merged` when it sees the merge, and starts an engine when the state changes. The engine then acts: merged sets `done` and cleans up, closed sets `aborted`, red CI sends the run to the fix stage with the check output as feedback, through the existing rework route. `done` is reached only after the merge.
  - Matches module 6's status table, module 11's merge-review row, and module 13's "6B routes on red CI".
  - Keeps every status write in the engine, under the lock.
  - Cost: a run's dashboard status stays `awaiting_approval` after its work is done, and `_answered_stop` needs a merge-review case, since merge review has no decision file.
- **`done-at-pr-open`**. Keep `done` when the pull request opens. `tick` polls done runs that have an open pull request. Red CI reopens the run.
  - Cost: `done` stops being terminal. The housekeeping row for `done` has to exclude runs with open pull requests. Reopening needs a status write from outside the lock holder, or an engine start that writes it, which is a second route to the same change.
  - Does not match module 6's status table.
- **`tick-acts`**. Keep `done` and add no state. `tick` calls `watch_pr`, then calls the retry, goto and finish paths itself.
  - Cost: `tick` writes run status, which breaks the lock rule. Red-CI routing moves out of the engine, so module 8's rework rules would apply in two places.

## Consequences

Whichever option is accepted:

- The engine, not the tick, decides what a red check means. The check output goes into the feedback record that module 8 already defines.
- The auto-merge calls (`evaluate_merge`, `merge_or_request_review`) get a caller in the same change, or a separate ADR names the wave that adds it.
- `tick.py`'s `unsupported` list shrinks only when the chosen option is built and tested.

## What was built

- `Engine._finish` parks a run that has a pull request, with a `merge_review` attention item.
- `Engine._merge_review` handles merged (done, worktree removed), closed (aborted) and red CI (`rework.route_red_ci`, loop key `<stage>-><goto>:ci`, limit from the last stage's `on_fail`). Open with green or pending CI changes nothing.
- A run that has just parked is not polled again by the same engine, because GitHub may not have seen the push yet. The next tick reads it.
- `tick` takes a `prs_for` argument so tests pass a fake. The tick report no longer has an `unsupported` list.
- Tests: `factory/engine/tests/engine/test_merge_review.py` (10) and the new cases in `factory/launcher/tests/test_tick.py`.

## Not built

- `evaluate_merge` and `merge_or_request_review` still have no caller on a live run. `evaluate_merge` needs `ci="green"`, and a pull request that has just opened is never green, so calling them at open time always chooses human review. When they should run (on the first green CI, from the tick) is a separate decision.
- The poll has run only against `FakePullRequests`. `gh pr view` through a real GitHub has not run.
- A red check on a workflow with no `on_fail` edge on its last stage blocks the run. `chore` and `bug-fix` both have one.
