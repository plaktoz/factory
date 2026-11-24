---
scope: repo
repo: factory
topic: a-repo-may-choose-codex
status: proposed
supersedes: [2026-11-14-codex-moves-to-phase-2]
---

# A repo may choose Codex as its harness

## Decision

Question for the owner: the owner chose, on 2026-11-24, that a repo may set `harness: codex`. That reverses the row "The Codex worker adapter is out of phase 1 and tracked here" in `docs/design/phase-2.md` (id `2026-11-14-codex-moves-to-phase-2`). Do you confirm that the row is replaced, and in what order is it built?

Recommended: **confirm the reversal, and build it behind the proofs that are still open** (option 1 below). The choice was the owner's and not the recommendation of the page, which recommended refusing Codex everywhere.

If the owner confirms: the repo-config schema accepts `codex`, `api.default_workers` builds a Codex worker for it, section 3 and phase 1 text say Codex may be chosen, and the old row in `phase-2.md` is replaced by a row that cites this ADR.

## Context

Facts checked by running or reading on 2026-11-24 (`main` at `984e533`):

- A repo's `factory.yaml` is checked by `factory/schemas/factory-config.schema.json`, where `harness` is `{"enum": ["claude"]}`. Running the check with `harness: codex` gives `'codex' is not one of ['claude']`.
- The machine-level check `loadcfg.resolve_harness` already accepts `claude` and `codex` (`test_codex_harness_resolves` passes).
- `api.default_workers` builds only `ClaudeAdapter` and raises `config.invalid` for any other harness.
- `CodexAdapter` exists (`factory/engine/factory_engine/adapters/worker/codex.py`) and is tested against a stub. Its D7 risk (one sandbox layer, `srt` only) is already accepted for Codex workers only (module 9).
- Open criteria in `phase-2.md` P2-1, all unticked: which flags keep a user's own `~/.codex` config and MCP servers out of a worker; the same gate evidence on Claude and Codex; a live Codex smoke run with `FACTORY_LIVE=1`; the router skill from Codex.

## Options considered

1. **Confirm the reversal and build it behind the open proofs (recommended).** Add `codex` to the schema and `default_workers` in one change, with a test that a repo with `harness: codex` loads and starts a Codex worker on the fake. Keep the four open criteria unticked and name them in the PR; do not call Codex ready until they pass. For: it is what the owner chose; the adapter is already merged. Against: it reopens a settled row and makes an untested path reachable; MCP isolation for Codex is unproven.
2. **Keep Codex refused everywhere (the page's recommendation).** Every check says "Codex is phase 2". For: matches the old row; nothing unproven is reachable. Against: the merged adapter and its tests stay unreachable; the owner chose against it.
3. **Allow it only on the machine, not in a repo's config.** `loadcfg` already does. For: smallest change. Against: it makes a repo that sets `harness: codex` fail while the machine accepts it, which is today's inconsistency.

## Why

The owner made the choice, so option 2 is not available; option 3 leaves the contradiction in place. Option 1 closes it, and naming the four unproven criteria keeps the cost visible.

## Consequences

- The old row in `phase-2.md` is replaced in the commit that accepts this ADR. The new row in `docs/process.md` (`2026-11-24-allow-codex`) moves into the spec the rule belongs to (module 3) and is deleted from `docs/process.md`.
- Text to update: `AGENTS.md` (Build order), `phase-1.md` (lines 15, 55, 81, 130), `phase-2.md` (P2-1 and its table), module 3 (the `harness` line).
- Not built by this ADR: the schema and `default_workers` change (`docs/tasks.md` item 55), the four open criteria.
- Supersedes: `2026-11-14-codex-moves-to-phase-2`.

## Source

Written 2026-11-24 from the decision page "Owner decisions, 2026-11-24 (backlog review)", decision D3, option `allow-codex` (not the recommended option), answered in the session. The card text is copied above, so the page is not needed to read it.
