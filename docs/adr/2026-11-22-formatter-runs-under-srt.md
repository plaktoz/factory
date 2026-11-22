---
scope: repo
repo: factory
topic: formatter-runs-under-srt
status: proposed
supersedes: []
---

# Should the formatter run under srt, like a cmd task?

## Decision

Question for the owner: when the engine formats a task's changed files after its worker stops (owner decision D8, 2026-11-22), should the formatter run under `srt`, the sandbox every `cmd` task and gate command already runs under (module 9), or stay a plain subprocess?

Recommended option: **run it under srt**. If the owner accepts, `run_step` in `factory/engine/factory_engine/toolchains.py` wraps each formatter argv with `sandbox.srt_command`, the same way `CommandAdapter` does, and its tests run the real formatter path.

## Context

- Today `run_step` calls `subprocess.run` with no sandbox (`toolchains.py`, the `run_step` body). The module doc of `toolchains.py` now says so, and the 17A spec does not claim a sandbox for formatting.
- The formatter is not a worker. It runs repo-controlled tools (for example a prettier config the worker wrote, or a Gradle wrapper script in the repo), with the engine's own `HOME`.
- A `cmd` task and a gate command already run under `srt` (module 9, "Every `cmd` task and gate command runs under `srt`"). `check_lint_clean` runs `format_check` and `lint` unsandboxed too, so the gap is the same for both.
- Checked by running: `srt` 0.0.83 is installed here and `canary_srt` passes on this machine (`tests/workers/test_command_adapter.py`, 4 passed on 2026-11-22).

## Options considered

1. **Run formatters and lint under srt (recommended).** For: matches the rule for every other command the factory runs; closes the gap for both the format step and `check_lint_clean`. Against: each formatter call pays the srt startup cost; a formatter that needs a file outside the worktree (a shared cache) must be allowed explicitly; the srt settings for a formatter differ from a worker's.
2. **Keep formatters unsandboxed and say so in the spec.** For: no change; the formatter is the repo's own tool, which the repo already runs in its own CI. Against: the factory's sandbox rule has an exception with no reason written down, and a repo config can run code with the engine's `HOME`.
3. **Sandbox only the format step, not lint.** For: smaller change. Against: lint and format share the same risk, so this splits one rule into two.

## Why

The factory's rule is that every command it runs goes through the sandbox (module 9). Option 1 keeps that rule without an exception, and the cost is one wrapper around `run_step`, which both steps already call. The decision is the owner's because it changes per-task cost and the sandbox rule.

## Consequences

- If accepted: `run_step` and `check_lint_clean` route through `srt`, with a test that a formatter's write outside the worktree is refused. The 17A criterion on formatting gains that test. The task is built after the owner's answer, not now.
- If option 2 is accepted: write the exception as a `Decisions` row in module 17A and in module 9's "Threat model" section, with its risk.
- Not built by this ADR. The D8 change (format after each worker) is already built and tested without the sandbox.

## Source

Written 2026-11-22 by the session that recorded owner decisions D1 to D8 from the decision page `owner-calls-2026-11-22` (`.scratch/owner-calls-2026-11-22.json`, not committed). The sandbox question came up in an independent review of the D8 change, not on the page, so it has no card. Options 1 and 3 were checked against `toolchains.py`, `check_lint_clean` and module 9's rule.
