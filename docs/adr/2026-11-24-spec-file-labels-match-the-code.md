---
scope: repo
repo: factory
topic: spec-file-labels-match-the-code
status: proposed
supersedes: []
---

# How should the 10 pending signatures that are not phase 1b come to agree with the code?

## Decision

Question for the owner: `test_signatures_match_spec.py` reports `built: 143  pending: 12`. Two of the 12 are unbuilt on purpose (`enable_plugin` and `disable_plugin`, phase 1b). The other 10 are pending for three different reasons, and a relabel alone does not fix them. Which fix do you want?

Recommended option: **fix the spec to say what the code does, in two steps.** Step 1, now: relabel the five signatures that exist and fix the three that differ. Step 2, later: decide the four launcher signatures and the two with no code.

## Context

The 10, checked against the code on 2026-11-24 (`main` at `f9d07b7`):

- **Built, wrong label, and the spec differs from the code (3).** `resolve_harness` (`loadcfg.py:69`) has two extra keyword-only parameters, `stage_model` and `task_model`. `validate` (`validate.py:35`) has an extra keyword `file`. `FakeWorkerAdapter.__init__` (`adapters/worker/fake.py:32`) has an extra `capabilities` keyword. With the right file label, the spec test fails on all three. Module 9 line 195 labels the block `# adapters/worker/claude.py, fake.py`, and the reader (`spec_signatures.py:22`) takes the first name only.
- **Built, wrong label, and the spec matches (2).** `load_config` (`loadcfg.py:41`) and `mask` (`redact.py:8`).
- **No code under that name (2).** `worktree_path` is in the spec's `config.py` block. The code has no such function: the logic is the private `gitops._worktree_for` (`gitops.py:114`) with `paths.render` underneath, and the name `worktree_path` exists only as a helper inside a test. `schedule_install` is in module 16's block, and no code has it: `schedule.py` has `install`, with a different signature.
- **Launcher functions the engine's test cannot see (3).** `tick` (`tick.py:165`) and `install_once` (`schedule.py:210`) exist. `dispatch` exists only as the private `_dispatch` (`cli.py:71`), with different parameters. Module 16 labels the block `# api.py`, which is the engine's file, and writes `# launcher (machine)` as a plain comment that the reader does not read as a file. The engine's environment cannot import `factory_launcher` (`ModuleNotFoundError`, checked 2026-11-24).
- Section 18 (`docs/design/shared/18-shared-contracts.md`, line 12) says `config.py` and `kit.py` are module 3's files. AGENTS.md lists a change to section 18 as ask-first. `config.py` holds only the `Config` type, and `loadcfg.py` imports it, so moving the functions back into it would be circular.
- Only `test_signatures_match_spec.py` reads the file label (`sig.file`, lines 31, 62 and 121). Nothing else in `scripts/` uses it. Not checked: readers outside `scripts/`.
- `enable_plugin` and `disable_plugin` are phase 1b: `factory plugins enable|disable` does not exist yet (module 16 line 98), so they stay pending.

## Options considered

1. **Fix the spec to match the code, in two steps (recommended).** Step 1: relabel `load_config`, `resolve_harness`, `validate`, `mask` and `FakeWorkerAdapter.__init__` to their real files, teach the reader a label that lists several files, and add the three extra parameters to the spec. Step 2: for `worktree_path`, `schedule_install` and `dispatch`, either rename the spec to the code (`gitops`'s helper, `schedule.install`, `_dispatch`) or write the function the spec names; and put the launcher on the contract test's path. For: the spec then says what a builder will find, and the check covers 5 more signatures at once. Against: edits section 18's file table and modules 3, 9 and 16; step 2 includes a choice between renaming spec text and writing code, and a path or a dev-group change for the launcher, which is a new dependency.
2. **Move the code into `config.py` and match the spec exactly.** For: the spec stays as written. Against: undoes the split into `loadcfg.py`, `validate.py`, `redact.py` and `paths.py`; every importer changes; the `Config` import becomes circular; the three extra parameters would be removed, which breaks the tests that pass them (`stage_model` and `task_model` are passed only in `tests/config/test_config.py`; no engine code passes them).
3. **Leave it, and keep the count of 12.** For: no change. Against: the check says nothing about 10 signatures, and three of them have drifted from the spec already, which this check was built to catch.

## Why

The spec is the thing that drifted: three signatures gained parameters that the spec never listed, and two spec names have no code. Option 2 would change working code to match stale text. Option 1 changes text and keeps the code that is tested and in use. Doing it in two steps keeps the safe part (labels and three parameter lists) apart from the part that needs a choice (what to do about a name with no code).

## Consequences

- If option 1, step 1 is accepted: five signatures move from pending to checked, and the count falls from 12 to 7. The remaining 7 are `enable_plugin`, `disable_plugin`, `worktree_path`, `schedule_install`, `dispatch`, `tick` and `install_once`. The pin on the signature count (`== 155`) does not move, because it counts spec signatures, not files.
- Step 2 is a second change, and it may need a new ADR if it adds a dependency or changes a signature other work reads.
- If option 2: the tests that pass the extra parameters stop working, and the number of files drops.
- If option 3: the three drifted signatures are never caught.
- Supersedes: none.

## Source

`scripts/docs-check/spec-contracts/test_signatures_match_spec.py` (`built: 143  pending: 12`, run 2026-11-24, and the check on a relabelled copy, run in a separate process without writing to the repo); `scripts/docs-check/spec-contracts/spec_signatures.py` (the label rule, line 22); `factory/engine/factory_engine/loadcfg.py`, `validate.py`, `redact.py`, `gitops.py`, `adapters/worker/fake.py`; `factory/launcher/factory_launcher/cli.py`, `tick.py`, `schedule.py`; `docs/design/shared/18-shared-contracts.md` line 12; `docs/design/modules/03-kit-and-configuration.md` line 218; `docs/design/modules/09-worker-adapters-and-governed-helpers.md` line 195; `docs/design/modules/16-drivers.md` lines 48, 64, 70 and 98.
