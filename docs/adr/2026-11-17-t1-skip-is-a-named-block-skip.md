---
scope: repo
repo: factory
topic: t1-skip-is-a-named-block-skip
status: accepted
supersedes: []
---

# `factory skip --gate no-test-results` passes the T1 block, and only it

## Decision

Accepted by the owner on 2026-11-17: option A, a skip name only for T1. `factory skip <run> --gate no-test-results --reason "..."` passes the block a verify stage raises when its tasks report 0 test cases (decision T1, module 8). No workflow edit is needed, and no shipped gate becomes skippable.

The engine accepts the name only when the run's latest `run_blocked` event carries `code: gate.no_test_results`. On any other block, such as failing tests past the rework limit on the same stage, the skip is refused and the run stays blocked. A T1 skip acts like any other skip. It logs `gate_skipped` with `gate: no-test-results` and the reason, marks the verify stage `skipped`, and turns off auto-merge. The blocked card's command is this skip, not `factory retry`.

This is one stated exception to the module 5 and module 8 rule that `factory skip` passes only a gate marked `skippable: true`.

## Context

T1 (`docs/reviews/test-results-decisions.md`) says `factory skip` passes the no-test-results block for a repo with no tests. As built in item 12, the block is raised by the engine in the verify join, before the stage's gates run. It is not a gate in the workflow, so `skip` found no gate to pass. `tests/engine/test_t1_skip.py` was a strict xfail that showed this.

## Options

- **A `t1-only-skip-name`** (chosen): a skip name that works only on the T1 block. The card shows the exact command. It cannot be used to skip failing tests. Cost: one exception to the skippable-only rule.
- **B `skippable-test-report`**: a repo marks `{schema: test-report, skippable: true}` in its own workflow. Almost no code, but the flag also lets a person skip real test failures, and T1 then needs a workflow edit first.
- **C `has-test-results-check`**: a new `{check: has-test-results}` gate that fails to a block, marked skippable in a repo override. It keeps the rule, but T1 still needs a workflow edit, and the check must run before the test-report gate.

## Consequences

- `Routing` carries an optional `code`, and `run_blocked` events carry it. `rework.block` takes the code and the card's command.
- The T1 `gate_failed` event names the gate `no-test-results`, the name `skip` takes. It was `test-report`.
- Any skip marks the whole stage skipped. In bug-fix, a T1 skip also skips `scripts/repro-now-passes.sh`. Auto-merge is off for the run either way.
