# Phase 1 decisions

Made on 2026-11-14 from `phase-1-decisions.html`. All 14 took the recommended option. Each is applied in the phase 1 spec (`docs/design/phase-1.md` and the module files it links).

| # | Decision | Chosen |
| --- | --- | --- |
| D1 | Run lock | OS file lock held for the process lifetime; heartbeat is display only; leftover worker process groups are killed before a new attempt |
| D2 | Exit codes | A `cmd` task exiting non-zero is a check failure; the engine checks the binary first. Plugin scripts keep 0, 1, 2 |
| D3 | Dependent tasks in a stage | A task branches from its dependency's branch; the join applies each task's own diff in `needs` order |
| D4 | Approvals on rework | One decision file per stage and visit: `decisions/<stage>.<n>.yaml` |
| D5 | Dashboard writes | Per-session token, plus Host and Origin checks |
| D6 | Operating systems | macOS and Linux in phase 1; Windows in phase 2 |
| D7 | Worker isolation | Changed 2026-11-14 (see below). Was: tool allowlist, scrubbed environment, denied reads, no OS sandbox. Now: those, plus Claude Code's own sandbox setting on for every worker; reads of secrets denied; writes only to the worktree and `$FACTORY_TASK_DIR`; `doctor` runs the canary each time |
| D8 | Personal setup | CLI flags keep your plugins, hooks and MCP servers out; a `doctor` probe worker verifies it |
| D9 | Skills | The factory writes its own headless skill for every stage; upstream skills are reference only |
| D10 | Scope | Phase 1a walking skeleton first, 1b adds the rest |
| D11 | Kit per run | Snapshot `factory/` and `.factory/config/` from the base branch when the run is created |
| D12 | Crash recovery | Reset the task worktree to the last checkpoint; the discarded diff is saved |
| D13 | Outages | After three tries the run is `retrying`; each tick retries for `infra_wait_hours` (6) before blocking |
| D14 | Notes | Restart with `progress.md`; harness session resume is not used in phase 1 |

## Open

- Login sessions (OAuth): out of scope. Phase 1 supports a key or gateway token only (decision of 2026-11-14, [open decisions](open-decisions.md)).
- Whether the sandbox works on Linux (Claude Code names `bwrap` for it). Not tested. A pre-pilot check: `doctor` must pass the canary on Linux before the phase 1a pilot.
- A worker's MCP servers with the sandbox on: tested on 2026-11-14 on macOS and they work. See [open decisions](open-decisions.md).
- What `failIfUnavailable` changes on a machine whose sandbox cannot start: not separable by the nested test, because the command failed with the flag off too. Each failure type has its own error code, found by testing (section 18).
- `sandbox-exec`, which Claude Code uses on macOS, is marked DEPRECATED in its man page. `doctor` proves the boundary on each machine.
- Readiness gaps that the four decisions did not close: G2 (module-local types), G3 (error-code catalogue), G9 (Python floor), and `RunSpec` from G7, which the review lists but gives no shape. See [open decisions](open-decisions.md).
- Codex moved to phase 2 on 2026-11-14; its open checks are in `docs/design/phase-2.md` (P2-1).

## Evidence (2026-11-14)

- D7 canary test, Claude Code 2.1.325, `--permission-mode dontAsk`. A file outside the worktree was read through each route with a Read deny rule on its path:
  Read tool direct: blocked. Read tool via symlink: blocked. `cat` with a narrow allowlist: blocked (confined to the working directory). `python3` allowed: **read it**. Unrestricted `Bash`: **read it**. No Bash tool: blocked.
  So a deny rule covers only the Read tool, and an allowed interpreter bypasses it. Absolute-path rules need a `//` prefix; a single `/` is relative to the project and silently matched nothing.
- Login: `claude auth status` reports a stored login only through the gateway token; with the gateway variables removed it reports `loggedIn: false`, and there is no keychain item. This machine has no OAuth login to test carry-over with.

- Claude Code 2.1.325: isolation flags exist; without them a headless worker received the global `CLAUDE.md`, with `--setting-sources project --strict-mcp-config` it did not.
- Diagrams: the six images in the docx were redrawn as Mermaid, parsed with Mermaid 11, and rendered to PNG. Five are in the spec; the dashboard wireframe is a table.

## D7 changed (2026-11-14)

D7 was accepted with no OS sandbox. The canary test above showed that a Read deny rule stops only the Read tool, so on 2026-11-14 the owner chose option `claude-sandbox` on the decision page `open-decisions.html`: turn on Claude Code's own sandbox setting for every worker, deny reads of secrets, allow writes only to the worktree and `$FACTORY_TASK_DIR`, and have `doctor` run the canary each time. The other two options were the factory's own `sandbox-exec` and `bubblewrap` wrapper, and keeping D7 as accepted. D1 to D6 and D8 to D14 are unchanged. Applied in [module 9](../design/modules/09-worker-adapters-and-governed-helpers.md) and the [phase split](../design/phase-1.md#phase-split) wording.

Evidence from 2026-11-14, Claude Code 2.1.325, macOS, gateway token, `--permission-mode dontAsk`, a planted file outside the worktree. Without the sandbox, `python3` read it. With the sandbox settings, `python3` failed with `Operation not permitted`, and so did the Read tool (a deny rule, with the `/` and the `//` form both blocking in this test) and `cat`. The `cat` call was refused by the permission layer before it ran, so this test does not show that the sandbox alone would stop `cat`. Writes with `python3` succeeded in the worktree and the task folder and failed outside both. `git status`, `git diff` and `git add` worked in a git worktree. A path under `allowRead` was readable while its denied parent was not. An outbound request from Bash to `example.com` was blocked.

Not tested: Linux (a pre-pilot check). Out of scope: an OAuth login. Tested since this note was written: MCP servers under the sandbox, and a sandbox that cannot start (see [open decisions](open-decisions.md)). The setting names exist in the 2.1.325 binary and can change between releases.

## Pilot repo decisions (P1 to P4)

Made on 2026-11-14 from `pilot-repo-decisions.html` (source `pilot-repo-decisions.json`, kept beside this file). The pilot repo is `plaktoz/test-adapters`. All four took the recommended option, and none held an open question. Each is applied in the phase 1 modules.

| # | Decision | Chosen | Applied in |
| --- | --- | --- | --- |
| P1 | Commits the engine makes without a request | Checkpoints stay on a local task branch that is never pushed; only the join commit is pushed. No switch to turn them off, because D12 recovery and note delivery need them | [7](../design/modules/07-git-and-github-operations.md), [3](../design/modules/03-kit-and-configuration.md) |
| P2 | Run state and worktrees against the repo's worktree rule | Cleanup runs the repo's `cleanup_check` first and skips removal when it fails | [17](../design/modules/17-housekeeping.md), [3](../design/modules/03-kit-and-configuration.md), [7](../design/modules/07-git-and-github-operations.md) |
| P3 | When the pilot starts | Phase 1a, with one chore or bug-fix issue and a human merge; feature work in 1b | [phase split](../design/phase-1.md#phase-split), [13](../design/modules/13-delivery.md), [plan](../design/shared/20-dependencies-and-plan.md) |
| P4 | Which model the engine records | Leave `model` unset; store the models the harness result reports | [9](../design/modules/09-worker-adapters-and-governed-helpers.md), [14](../design/modules/14-token-tracking.md) |

Evidence for P4, from a real `claude -p --output-format json` call on Claude Code 2.1.325 through the gateway: the result has no top-level `model` key. It has `modelUsage`, keyed by the model name the gateway returned (here `claude-advantage-assist`), each with its own token counts. A run with subagents can have several keys, so the usage record holds a list.

Evidence for P2: the pilot repo's `AGENTS.md`, "3. Do the work", says not to remove a worktree until `git status` is clean, and to compare each changed file with the committed or merged file before `git worktree remove --force`.

Still open from this round: whether the repo's comparison can be a single command. The spec treats it as one (`cleanup_check`, exit 0 means safe); the pilot repo has no such script yet, so the pilot sets none and every worktree that is not clean is skipped and reported until it adds one.

## Decisions before wave 0 (R1 to R3 and D7)

Made on 2026-11-14 from `open-decisions.html`. All four took the recommended option. The record of each, with the files it changed, is in [open decisions](open-decisions.md).

## Moved to phase 2 (2026-11-14)

Codex moved out of phase 1, tracked as P2-1 in `docs/design/phase-2.md` with the adapter design, what phase 1 keeps so it is cheap to add, and the checks still to run.

## Structure (2026-11-14)

The spec is split one file per module; see `docs/adr/2026-11-14-one-file-per-module.md`. Pilot repo decisions P1 to P4 are logged above, with their source in `pilot-repo-decisions.json` and its generated page.
