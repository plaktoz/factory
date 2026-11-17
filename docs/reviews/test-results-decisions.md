# Test results in a real bug-fix run: notes

Page: `docs/reviews/test-results-decisions.html`. Data: `docs/reviews/test-results-decisions.json`. Asked on 2026-11-17 from `docs/tasks.md` item 12.

## Settled by the spec, not asked

- Who turns the verify tasks' JUnit files into the `test-report`: the engine, with `write_test_report` (module 5, report schemas table). The code never calls it; that is a build task.
- How `cmd` tasks and `cmd` gates run: through `CommandAdapter` under `srt` (module 9, "Deterministic tasks"; module 8, "Gate commands run sandboxed"). Checked on 2026-11-17 by running the engine: the first task of every run (`rules`, `cmd: [factory, triage]`) is handed to the worker registered as `claude`, and a `cmd` gate with no runner installed raises `config.invalid: a cmd gate needs module 9's CommandAdapter, which is not built`. Not tried: what a live Claude worker does with a command it is handed.

## Owner's answers (2026-11-17)

| Decision | Choice | Recommended? | Applied in |
| --- | --- | --- | --- |
| T1 When a bug-fix run's tests report nothing, what should you get? | `stop-on-zero-tests` | Yes | [Module 8](../design/modules/08-gates-error-handling-and-rework.md): a "No test results" row in the class table and an unticked criterion; `docs/tasks.md` item 12 |
| T2 When should real bug-fix runs start working? | `wire-commands-next` | Yes | `docs/tasks.md`: item 12 becomes the next task, ahead of the four open module 16 criteria |

T1 means: when the verify stage's tasks together report 0 test cases (no JUnit file, or files with no test case), the run is blocked with a reason naming the missing files, so no pull request opens. `factory skip` passes it for a repo with no tests, and a skip turns off auto-merge for that run (module 8, existing rule). Built in item 12. The skip is `factory skip <run> --gate no-test-results`, chosen by the owner on 2026-11-17 as option A (ADR `docs/adr/2026-11-17-t1-skip-is-a-named-block-skip.md`).

T2 orders work only. Nothing is built by this answer.
