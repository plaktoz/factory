---
scope: repo
repo: factory
topic: no-test-results-stops-the-run
status: accepted
supersedes: []
---

# A bug-fix run whose tests report nothing stops

## Decision

When the verify stage's tasks report 0 test cases together, the run is blocked before a pull request opens. The block names the missing result files (code `gate.no_test_results`). The factory never opens a pull request whose summary says the tests passed when no test ran.

Chosen option: `stop-on-zero-tests`.

## Context

When a test command ran but wrote no result file (a wrong path, or a runner that writes none), the "Tests N passed" line of the pull request was missing, and nothing said why. The report built from no result file says 0 tests and 0 failed, and it passed the check (checked 2026-11-17). Built in item 12 of `docs/tasks.md`. A repo with no tests can skip the block with `factory skip`, under [the T1 skip ADR](2026-11-17-t1-skip-is-a-named-block-skip.md).

## Options considered

- **`stop-on-zero-tests`** (chosen, recommended): the run stops and asks. Cost: a repo with no tests stops until it adds one or skips the check, and a skip turns off auto-merge for that run.
- **`pass-and-warn`**: the pull request opens with a line saying no tests were found. Cost: with auto-merge on, a change with no tests run can merge unseen.
- **`pass-silently`**: no change from today. Cost: "no tests ran" and "all tests passed" look the same.

## Source

Answered on 2026-11-17 on page `746ec67:docs/reviews/test-results-decisions.json` (the folder was deleted after that commit), decision `T1`, option `stop-on-zero-tests`, which was the recommended option. The owner's answer is the record's, not new.
