---
scope: repo
repo: factory
topic: cmd-tasks-run-through-command-adapter
status: accepted
supersedes: [2026-11-17-cli-end-to-end-test-runs-bug-fix]
---

# `cmd` tasks run through CommandAdapter, not the worker

## Decision

A deterministic task (`cmd`, `script` or `python`) runs through `CommandAdapter` under `srt`. A skill task runs through the worker registered for its harness. The engine picks the adapter per task (`engine._worker_for`). Each `cmd` task writes its own `out` file into its task folder, and `CommandAdapter.wait` returns that file as the artifact.

This supersedes what ADR `2026-11-17-cli-end-to-end-test-runs-bug-fix` says about `cmd` tasks. That ADR states that the engine hands `cmd` tasks to the worker and that the scripted worker runs them. That was true of the code when it was written, and it is no longer true. Its choice of the bug-fix end-to-end test with stubbed gates still stands. Only the `cmd`-task part is replaced.

## Context

Item 12 in `docs/tasks.md` found that every task went to the one registered worker. So the first task of every run, `rules` (`cmd: [factory, triage]`), and every verify `cmd` task went to Claude. Module 9 says deterministic tasks use `CommandAdapter`. The owner approved the change on 2026-11-17 (option 1, with the three approvals recorded in the item 12 Log entry).

## Consequences

- The end-to-end tests split their fakes. `cmd` tasks (`rules`, `check`, and the verify tasks `be-tests`, `fe-tests`, `e2e`) go to a command fake. Skill tasks go to the worker fake. A test that checks the split asserts each fake's task list.
- The verify fixture writes JUnit XML. The old JSON fixture was read as no test cases, which T1 blocks, so the test had been passing only because nothing counted its tests.
- The M2 ADR's statement that `cmd` gates go through `gates.use_command_runner` still holds. A stub still replaces the runner in tests.
- Not checked by these tests: a live Claude worker given a `cmd` task. The owner has not asked for it, and the question stays open in `docs/reviews/test-results-decisions.md`.
