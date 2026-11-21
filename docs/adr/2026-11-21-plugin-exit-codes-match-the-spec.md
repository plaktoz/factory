---
scope: repo
repo: factory
topic: plugin-exit-codes-match-the-spec
status: accepted
supersedes: []
---

# The plugin runner's exit codes match module 5

## Decision

Accepted by the owner on 2026-11-21, in the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them: make the plugin exit codes match the spec.

A plugin task exits 0 when it passes, 1 when its check fails, and 2 for a task error. A result with no `status` is decided by `passed`: true is 0 and false is 1. A function that raises or calls `sys.exit`, a result that cannot be written as JSON, and anything that stops the plugin from loading are all exit 2.

## Context

The runner treated a result with no `status` as passed, even when `passed` was false. It caught `Exception` only, so `sys.exit` in a plugin, or at import, escaped the task-error path. It let a result that was not JSON raise. The code is `plugin_runner.py`; the rule is in module 5, under the plugin exit codes.

## Options considered

- **Change the code to match the spec (chosen).**
  - The walkthrough's option list is not in the repo, so no alternatives are listed. This record states the answer the owner gave.

## Why

A check that reports `passed: false` must not pass the gate.

## Consequences

- Tests in `factory/engine/tests/workers/test_plugin_runner.py`, including `test_a_result_with_passed_false_and_no_status_is_a_check_failure` and `test_sys_exit_inside_the_function_is_a_task_error`.
- Not tested: a plugin `cmd`, `script` or `python` task run through the engine to its artifact. Module 5 keeps that criterion unticked.
- Commit `6a69067`, PR #73.

## Source

Written on 2026-11-21 by Claude Code from the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them. The answer is the owner's, not new.
