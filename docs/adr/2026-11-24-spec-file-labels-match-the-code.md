---
scope: repo
repo: factory
topic: spec-file-labels-match-the-code
status: proposed
supersedes: []
---

# Should the spec's file labels name the files the code lives in?

## Decision

Question for the owner: `test_signatures_match_spec.py` reports `built: 143  pending: 12`. Two of the 12 are unbuilt on purpose (`enable_plugin` and `disable_plugin`, phase 1b). The other 10 are built, but the spec labels them with a file they are not in, so the check cannot see them. How should the labels and the code agree?

Recommended option: **change the spec's labels to the real files, and teach the reader two things**: a label may list several files (`# adapters/worker/claude.py, fake.py`), and a block labelled `# launcher` is not a file of the engine package. Section 18's file table then names the real files for module 3.

## Context

- The 10, as the test prints them (run 2026-11-24 on `main` at `f9d07b7`):
  - `config.py`: `load_config`, `resolve_harness`, `worktree_path`, `validate`, `mask`. The code is in `loadcfg.py`, `paths.py`, `validate.py` and `redact.py`. `config.py` holds only the `Config` type, and `loadcfg.py` imports it.
  - `adapters/worker/claude.py`: `FakeWorkerAdapter.__init__`. The code is in `adapters/worker/fake.py`. Module 9 line 195 labels the block `# adapters/worker/claude.py, fake.py`, and the reader takes the first name only.
  - `api.py`: `dispatch`, `tick`, `schedule_install`, `install_once`. Module 16 labels the block `# api.py` and then writes `# launcher (machine)` as a plain comment, which the reader does not read as a file. The code is in `factory_launcher/cli.py`, `tick.py` and `schedule.py`, which are not in the engine package.
- Section 18 (`docs/design/shared/18-shared-contracts.md`, line 12) says `config.py` and `kit.py` are module 3's files. AGENTS.md lists a change to section 18 as ask-first.
- `config.py` cannot simply re-export the functions: `loadcfg.py` imports `Config` from `config.py`, so the import would be circular.
- The five module 3 functions are built, tested and in use; only their label is wrong. Nothing but this check reads the label.
- `enable_plugin` and `disable_plugin` are phase 1b: `factory plugins enable|disable` does not exist yet (module 16 line 98), so they stay pending.

## Options considered

1. **Relabel the spec and teach the reader (recommended).** For: the check then covers 6 more signatures now (4 more once the launcher is importable), and the spec names the files a builder will find. Against: edits section 18's table and the labels in modules 3, 9 and 16; the reader gains two small rules.
2. **Move the code into `config.py`.** For: the spec stays as written. Against: puts `load_config`, `validate`, `mask` and `worktree_path` in one file again, undoing the split that `loadcfg.py`, `validate.py`, `redact.py` and `paths.py` made; every importer changes; the `Config` import becomes circular.
3. **Leave it, and lower the check's expectation.** For: no change. Against: the count of 12 stays, and the check says nothing about 10 functions that are built.

## Why

The labels are the only part that is wrong. The code is split by what each function does, and that split is already tested. Option 1 changes a table and a reader, and no behavior.

## Consequences

- If accepted: the six engine signatures (the five module 3 functions and `FakeWorkerAdapter.__init__`) move from pending to checked, so the count falls from 12 to 6. The four launcher signatures (`dispatch`, `tick`, `schedule_install`, `install_once`) stay pending until the contract test can import `factory_launcher`, which the engine's environment cannot do today (`ModuleNotFoundError`, checked 2026-11-24). Making it importable is a second step: add the launcher folder to the test's path, or install it in the engine's dev group, which is a new dependency and the owner's call. The check then compares the signatures to the code; any that differ will fail, so a few spec lines may need a fix in the same change. The pin on the signature count (`== 155` in `test_signatures_match_spec.py`) does not move, because the count is of spec signatures, not files.
- If option 3: the 10 stay unchecked, and a change to one of them is never caught against the spec.
- Supersedes: none.

## Source

`scripts/docs-check/spec-contracts/test_signatures_match_spec.py` (`built: 143  pending: 12`, run 2026-11-24); `scripts/docs-check/spec-contracts/spec_signatures.py` (the file label rule, line 8); `docs/design/shared/18-shared-contracts.md` line 12; `docs/design/modules/03-kit-and-configuration.md` line 218; `docs/design/modules/09-worker-adapters-and-governed-helpers.md` line 195; `docs/design/modules/16-drivers.md` lines 48 and 64.
