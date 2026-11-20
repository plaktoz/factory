---
scope: repo
repo: factory
topic: which-engine-serves-each-repo
status: accepted
supersedes: []
---

# Which engine serves a repo's commands

## Decision

Accepted by the owner on 2026-11-21, on page `docs/decision-pages/which-engine-serves-each-repo.json`, decision `D1`: option `snapshot-engine-on-pythonpath`. The page calls it "Each repo brings its own engine".

A run uses the engine in its own kit snapshot. The snapshot is `$FACTORY_HOME/kits/<kit_hash>/`, and its engine is `kits/<kit_hash>/factory/engine` (checked, see Context). The launcher selects it by setting `PYTHONPATH` to that folder before it runs `python -m factory_engine`.

- A command about an existing run reads `kit_hash` from the run's `run.json` and uses that snapshot's engine. This covers `api.spawn_engine`, so an engine that `tick` starts is the run's own engine too.
- A command that creates a run uses the repo's committed kit (shared contracts, section 18).
- `init` and `upgrade` stop excluding `engine/`, so the repo's `factory/` folder, and every snapshot made from it, carries the engine. `KIT_KEEP` and its comment change.
- The engine's dependencies (PyYAML, jsonschema) still come from the launcher's environment. The per-snapshot virtual environment from `requirements.lock` is deferred to phase 1b. Until then, [module 3](../design/modules/03-kit-and-configuration.md) describes more than the code does, and module 3 says so.

Not chosen: `per-snapshot-venv` (needs a `requirements.lock` in every kit and a venv build for each snapshot) and `launcher-installed-engine` (a repo on an old kit would run newer engine code).

## Context

[Module 16](../design/modules/16-drivers.md) has an acceptance criterion: two repos on different kit versions are driven by their own engine through one launcher. Shared contracts (section 18) say the launcher hands each command about a run to "that run's own engine, `python -m factory_engine` from the run's kit snapshot", and that commands creating runs use "the repo's committed kit". [Module 3](../design/modules/03-kit-and-configuration.md) says the launcher starts a run's engine "from the snapshot with the virtual environment for that snapshot's `requirements.lock`".

The code does not do this. Checked on the `wave4/m16-criteria` branch:

- `factory_launcher/cli.py` `_dispatch` runs `sys.executable -m factory_engine` with `cwd=<repo>`. The launcher's interpreter has the engine installed editable from this repo's `factory/engine`, so it imports that engine, not the repo's. A stub engine placed at `<repo>/factory/engine/factory_engine` is never run. A `PYTHONPATH` that names the kit's engine does override the install, which is how a per-kit engine could be selected.
- `api.spawn_engine` runs the same `sys.executable -m factory_engine` call, so tick-started engines have the same problem.
- `kit.init_repo` and `kit.upgrade` copy `factory/` into the repo with `engine/` excluded (`KIT_KEEP = {"engine"}`: "the engine is installed by the launcher, not by init"). A repo's copy therefore has no engine to run.
- `gitops.snapshot_kit` copies the repo's committed `factory/` into `$FACTORY_HOME/kits/<hash>/`. Because `init` left `engine/` out, that snapshot has no engine either (checked on 2026-11-20: after `init_repo` and a commit, the snapshot holds `.factory` and `factory`, and `factory/engine` does not exist). Nothing starts an engine from a snapshot, and the kit has no `requirements.lock`, so no venv is built.
- [Module 3](../design/modules/03-kit-and-configuration.md) lists `engine/` in the kit layout, so the spec and `kit.py` disagree.

Checked again on 2026-11-21, by running code, not by reading it:

- In a scratch repo with a stub engine committed at `factory/engine/factory_engine`, `snapshot_kit` made `kits/<hash>/factory/engine/factory_engine/...`. The path is `kits/<hash>/factory/engine`. Commit `33b042c` wrote `kits/<hash>/engine`, which is wrong.
- With `PYTHONPATH` set to that folder, `import factory_engine` loaded the stub, not the editable install in the launcher's venv. Without it, the installed engine loaded. So the mechanism works as the ADR says.
- Callers: `cli.py` `_dispatch` has one caller, `_engine_passthrough`, which knows the run id or the repo. `api.spawn_engine` is called from `cli.py` and from `tick.py`.

So a repo on one kit version and a repo on another both run the one engine installed in the launcher's environment. Module 16 cannot mark the criterion done until one of the options below is built.

## Options considered

- **`launcher-installed-engine`**: Keep one engine, the launcher's installed one. Mark the criterion as not applicable for phase 1a and say so in module 16.
  - For: Nothing to build. Matches what runs today.
  - Against: Kit snapshots and `kit_hash` do nothing for engine selection. A repo on an old kit runs the new engine's code against old workflows and schemas, which module 3 forbids.
- **`snapshot-engine-on-pythonpath`** (recommended, accepted): Each engine process takes its kit folder from the run's `kit_hash`. `init` and `upgrade` stop excluding `engine/`, so the repo's kit and every snapshot carry it. The launcher sets `PYTHONPATH` to `$FACTORY_HOME/kits/<hash>/factory/engine` (or the repo's `factory/engine` for commands that create runs) before it runs `python -m factory_engine`. The venv for `requirements.lock` is deferred to phase 1b.
  - For: Uses the snapshot that already exists. A run keeps the engine it was created with. No new dependency.
  - Against: The snapshot's dependencies (PyYAML, jsonschema) come from the launcher's environment, so this is not yet the per-snapshot venv that module 3 describes. Every target repo commits a copy of the engine source, and `KIT_KEEP` and its comment change.
- **`per-snapshot-venv`**: Build a venv for each snapshot from its `requirements.lock`, and run the engine with that venv's interpreter. This is what module 3 describes in full.
  - For: Matches module 3 exactly, including dependency isolation between kits.
  - Against: Needs a lock file in every kit and a venv build on the first run of each snapshot. Larger than this criterion, and it adds a long-lived install step to `snapshot_kit`.

## Why

The owner chose the recommended option. It gives module 16's criterion a testable behavior: two repos with two stub engines, and the launcher runs each one's engine. It keeps the engine of a run tied to its snapshot, which module 3 requires, and it needs no new dependency or install step.

The cost is accepted: dependencies stay shared until phase 1b, and every target repo commits a copy of the engine source. Measured on 2026-11-21 with the `KIT_KEEP` exclusion removed and the existing ignore patterns kept, the engine folder is 128 files and 1.3 MB with its `tests/` folder, and 60 files and 0.6 MB without it. The first draft of this ADR said "58 files, 1.4 MB"; that count was not measured. Whether the copy should leave out `tests/` is a build detail for the follow-up task.

## Consequences

- Module 16's two-kit criterion can be ticked once a test drives two repos with different stand-in engines through one launcher. Until that test exists the criterion stays open.
- A launcher upgrade no longer changes the engine of a repo that is already on a kit. `factory upgrade` does.
- Module 3 and shared contracts section 18 describe the venv; each now says the venv is phase 1b and what runs until then.
- The code and config changes are a follow-up task in `docs/tasks.md` (item 17). None of them is built by this ADR.

## Source

Written on 2026-11-20 by the session finishing module 16, and accepted on 2026-11-21. Answered on page `docs/decision-pages/which-engine-serves-each-repo.json`, decision `D1`. Module 16's two-kit criterion stays unticked until the follow-up task is built and tested.
