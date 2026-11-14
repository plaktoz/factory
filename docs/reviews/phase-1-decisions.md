# Phase 1 decisions

Made on 2026-11-14 from `phase-1-decisions.html`. All 14 took the recommended option. Each is applied in `docs/design/phase-1.md`.

| # | Decision | Chosen |
| --- | --- | --- |
| D1 | Run lock | OS file lock held for the process lifetime; heartbeat is display only; leftover worker process groups are killed before a new attempt |
| D2 | Exit codes | A `cmd` task exiting non-zero is a check failure; the engine checks the binary first. Plugin scripts keep 0, 1, 2 |
| D3 | Dependent tasks in a stage | A task branches from its dependency's branch; the join applies each task's own diff in `needs` order |
| D4 | Approvals on rework | One decision file per stage and visit: `decisions/<stage>.<n>.yaml` |
| D5 | Dashboard writes | Per-session token, plus Host and Origin checks |
| D6 | Operating systems | macOS and Linux in phase 1; Windows in phase 2 |
| D7 | Worker isolation | Tool allowlist, scrubbed environment, denied reads of secrets, no GitHub token; residual risk stated; no OS sandbox |
| D8 | Personal setup | CLI flags keep your plugins, hooks and MCP servers out; a `doctor` probe worker verifies it |
| D9 | Skills | The factory writes its own headless skill for every stage; upstream skills are reference only |
| D10 | Scope | Phase 1a walking skeleton first, 1b adds the rest |
| D11 | Kit per run | Snapshot `factory/` and `.factory/config/` from the base branch when the run is created |
| D12 | Crash recovery | Reset the task worktree to the last checkpoint; the discarded diff is saved |
| D13 | Outages | After three tries the run is `retrying`; each tick retries for `infra_wait_hours` (6) before blocking |
| D14 | Notes | Restart with `progress.md`; harness session resume is not used in phase 1 |

## Open

- Whether a login session (not a gateway token) carries over with `--setting-sources project`. Test on a machine that uses OAuth login.
- Codex: `codex exec` has `-c key=value` config overrides, `-s` sandbox, `-p` profile and `--strict-config` (0.164.0). Its `--json` event stream and where token usage appears are not checked yet.
- Whether each harness enforces deny-read rules (D7).

## Evidence (2026-11-14)

- Claude Code 2.1.325: isolation flags exist; without them a headless worker received the global `CLAUDE.md`, with `--setting-sources project --strict-mcp-config` it did not.
- Diagrams: the six images in the docx were redrawn as Mermaid, parsed with Mermaid 11, and rendered to PNG. Five are in the spec; the dashboard wireframe is a table.
