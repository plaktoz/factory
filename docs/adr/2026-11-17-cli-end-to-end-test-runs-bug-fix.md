---
scope: repo
repo: factory
topic: cli-end-to-end-test-runs-bug-fix
status: accepted
supersedes: []
---

# The CLI end-to-end test runs bug-fix, with stubbed gates and a scripted worker

## Decision

The end-to-end CLI test runs the shipped `bug-fix` workflow on a seeded repo, driven only through the CLI. Its `cmd` gates are stubbed through `gates.use_command_runner`. Its worker is a scripted `FakeWorkerAdapter` and its pull request service is `FakePullRequests`. The run stops at the `propose` approval, is answered with `factory decide`, and finishes. The `chore` test stays beside it.

Chosen option: `bug-fix-stubbed-gates`.

## Context

The end-to-end test is the only test that drives a whole run through the CLI (`add`, `run`, then `decide`). The spec says it runs bug-fix. The build agent ran `chore` instead, because bug-fix needs a repro script, `make` targets, JUnit reports, a review and a human approval stop at `propose`. Phase 1a ships bug-fix and chore, and the pilot is one chore or bug-fix issue.

The page left two things unchecked: whether `cmd` tasks (`make test-api`) go through the same runner as `cmd` gates, and how many scripted artifacts bug-fix's schema and check gates need. Both are now checked:

- `cmd` gates go through `gates.use_command_runner`. `cmd` tasks do not: the engine hands them to the worker with `ctx.cmd` set, so the scripted worker runs them and writes their reports.
- Ten tasks need artifacts: `repro`, `cause`, `plan`, `backend`, `frontend`, `be-tests`, `fe-tests`, `e2e`, `standards` and `spec`, plus triage's `rules` task. Each stage task writes a `stage-report` whose claim cites `services/api.py:1`, a line the seeded repo has, so `evidence-cites-code` passes. The three verify tasks write a `test-report` under their `.junit.xml` names. The two review tasks write `review-findings` with one `low` finding, so `no-blocking-findings` passes.
- `FakeWorkerAdapter` reports `subagents="none"` by default, which splits `backend` into helper tasks (`backend-api-code`, `backend-tests`). The Claude adapter reports `native`, so the test gives the fake the same capability and `backend` stays one task.

## Options considered

- **`bug-fix-stubbed-gates`** (chosen) (recommended): Run the shipped bug-fix workflow, with its `cmd` gates stubbed and the worker scripted.
  - For: Meets the spec line, and tests the workflow the spec names
  - For: Bug-fix has the `propose` approval stop, so the test answers it with `factory decide` through the CLI and covers the command of [decide-answers-are-positional-tokens](2026-11-17-decide-answers-are-positional-tokens.md) end to end
  - For: It also drives the `on_fail` routing that only bug-fix has, through the CLI
  - For: Uses a seam that already exists, so no change to engine code
  - Against: The biggest fixture of the three: valid scripted artifacts for each stage and a stub for every `cmd` gate
  - Against: A stubbed gate proves the engine's routing, not that `scripts/repro-fails.sh` works, which no seeded repo can show
  - Against: If `cmd` tasks did not use the stub seam, the verify stage would need a second one (they do not use it; the worker runs them)
- **`keep-chore`**: Keep `chore` as the end-to-end run and change the spec line to say so.
  - For: Already built and passing
  - For: Chore's gates are met by a seeded repo with no stubs
  - For: Chore is a phase 1a workflow and a pilot workflow, so it is a real run
  - Against: Chore has no human approval stop, so no CLI test answers a stop with `decide` start to finish
  - Against: No CLI-level test of the retry-and-route path through `on_fail goto` on a stage that has a review
  - Against: Changes the spec to match the code, and the module 16 line was written with bug-fix in mind
- **`fixture-workflow`**: Add a small test-only workflow shaped like bug-fix (an approval stop, an `on_fail` route, one `cmd` gate).
  - For: Covers the approval stop and `decide` through the CLI with a fraction of bug-fix's fixture
  - For: Fast and easy to read, and it needs no schema-valid reports
  - Against: It is not a shipped workflow, so it does not show bug-fix loads and runs through the CLI
  - Against: The spec line still says bug-fix, so the spec changes anyway
  - Against: A fixture workflow can drift from bug-fix without a failing test

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

Only bug-fix has the approval stop, so running it through the CLI is the one test that shows a run stopping, being answered by `factory decide` and finishing.

## Consequences

- `test_a_bug_fix_run_stops_at_propose_is_answered_by_decide_and_reaches_done` (commit `cf63f57`) runs `add --no-run`, then `run` (exit 3, run `awaiting_approval` at `propose`, only `rules`, `repro`, `cause` and `plan` started), then `decide <run> --packet <sha> D1=approve`, then `run` again (exit 0, run `done`, all eleven worker tasks started, one pull request created). The `chore` test is unchanged.
- Checked that the test can fail: answering `D1=reject` fails it, and a stub that fails `make build` fails it (the run routes back to `root-cause`, which has no second scripted attempt).
- The test writes `test-report` JSON under each verify task's `.junit.xml` name because nothing in the engine converts JUnit files: `gates.write_test_report` has no caller, and the `schema: test-report` gate runs once per task against that task's own artifact. A live bug-fix run would fail that gate unless the worker writes the report itself. This is a gap in the engine, not in the test, and it is open in `docs/tasks.md`.
- This test does not tick a module 16 criterion. None of the open ones names the end-to-end test; the "Run and test" line already describes it.

## Source

Answered on 2026-11-17 on page `docs/reviews/m16-cli-decisions.json`, decision `M2`. The owner chose `bug-fix-stubbed-gates`, the recommended option, and the session's brief names it ("This is the M2 decision ... the end-to-end test runs bug-fix with stubbed `cmd` gates and a scripted worker"). The owner then asked for this ADR to be written (2026-11-17). The owner has not yet read its text, so `accepted` here rests on that answer; the owner can supersede it with a new ADR.
