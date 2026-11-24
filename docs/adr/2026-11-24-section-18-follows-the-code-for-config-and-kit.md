---
scope: repo
repo: factory
topic: section-18-follows-the-code-for-config-and-kit
status: proposed
supersedes: []
---

# Should section 18 name the files the config and kit functions really live in?

## Decision

Question for the owner: `docs/design/shared/18-shared-contracts.md` line 12 says module 3's files are `config.py` and `kit.py`. The functions the spec names live in `loadcfg.py`, `validate.py`, `redact.py` and `paths.py`. Which should change?

Recommended option: **the spec follows the code.** Section 18 names the four files the code really uses, and nothing moves in the code. If the owner accepts, the same commit changes section 18 and adds a `Decisions` row to the module 3 file.

## Context

- Checked by running `scripts/docs-check/spec-contracts/test_signatures_match_spec.py` on `main` (2026-11-24): `built: 143  pending: 12`. Several pending signatures are pending for this reason.
- `factory/engine/factory_engine/loadcfg.py` already imports the `Config` type from `config.py`. Moving the functions into `config.py` would make that import circular.
- Section 18 is a shared contract. AGENTS.md lists a change to it as a stop trigger, so it waits for the owner.

## Options considered

1. **The spec follows the code (recommended).** Section 18 names `loadcfg.py`, `validate.py`, `redact.py` and `paths.py`. For: no code moves, so no tested behaviour changes; the signature count drops for these names. Against: section 18 changes, and the file names appear in the spec.
2. **The code moves back to the spec.** The functions move into `config.py` and `kit.py`, and every importer changes. For: section 18 stays as written. Against: a circular import with `loadcfg.py`; the parameters that tests pass (`stage_model`, `task_model`) would be removed or moved; a large change to working code.

## Why

The spec drifted from the code. Changing working, tested code to match stale text carries more risk than changing the text, and the circular import makes option 2 hard to do cleanly.

## Consequences

- If option 1 is accepted: section 18's module 3 row changes; a `Decisions` row is added to module 3; the signature check reports fewer pending names. Task: edit section 18 and module 3 in one commit, then rerun the signature check.
- Not built by this ADR: the code move in option 2.
- Supersedes: none.

## Source

Written 2026-11-24 from the decision page `open-stops-2026-11-24` (`.scratch/open-stops-2026-11-24.json`, decision `D1`), which is deleted once this ADR is recorded. The full card text is copied into this file, so the page is not needed to read it.
