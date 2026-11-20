---
scope: repo
repo: factory
topic: which-engine-serves-each-repo
status: proposed
supersedes: []
---

# Which engine serves a repo's commands

## Decision

Not chosen. The owner picks one option below and the chosen option is written as an accepted ADR.

## Context

[Module 16](../design/modules/16-drivers.md) has an acceptance criterion: two repos on different kit versions are driven by their own engine through one launcher. Shared contracts (section 18) say the launcher hands each command about a run to "that run's own engine, `python -m factory_engine` from the run's kit snapshot", and that commands creating runs use "the repo's committed kit". [Module 3](../design/modules/03-kit-and-configuration.md) says the launcher starts a run's engine "from the snapshot with the virtual environment for that snapshot's `requirements.lock`".

The code does not do this. Checked on the `wave4/m16-criteria` branch:

- `factory_launcher/cli.py` `_dispatch` runs `sys.executable -m factory_engine` with `cwd=<repo>`. The launcher's interpreter has the engine installed editable from this repo's `factory/engine`, so it imports that engine, not the repo's. A stub engine placed at `<repo>/factory/engine/factory_engine` is never run. A `PYTHONPATH` that names the kit's engine does override the install, which is how a per-kit engine could be selected.
- `api.spawn_engine` runs the same `sys.executable -m factory_engine` call, so tick-started engines have the same problem.
- `kit.init_repo` and `kit.upgrade` copy `factory/` into the repo with `engine/` excluded (`KIT_KEEP = {"engine"}`: "the engine is installed by the launcher, not by init"). A repo's copy therefore has no engine to run.
- `gitops.snapshot_kit` copies `factory/` into `$FACTORY_HOME/kits/<hash>/`, and that copy does include `engine/`. Nothing starts an engine from it. No `requirements.lock` venv is built.

So a repo on one kit version and a repo on another both run the one engine installed in the launcher's environment. Module 16 cannot mark the criterion done until one of the options below is built.

## Options considered

- **`launcher-installed-engine`**: Keep one engine, the launcher's installed one. Mark the criterion as not applicable for phase 1a and say so in module 16.
  - For: Nothing to build. Matches what runs today.
  - Against: Kit snapshots and `kit_hash` do nothing for engine selection. A repo on an old kit runs the new engine's code against old workflows and schemas, which module 3 forbids.
- **`snapshot-engine-on-pythonpath`** (recommended): Each engine process takes its kit folder from the run's `kit_hash`. The launcher sets `PYTHONPATH` to `$FACTORY_HOME/kits/<hash>/engine` (or the repo's `factory/engine` for commands that create runs) before it runs `python -m factory_engine`. The venv for `requirements.lock` is deferred to phase 1b.
  - For: Uses the snapshot that already exists. A run keeps the engine it was created with. No new dependency.
  - Against: The snapshot's dependencies (PyYAML, jsonschema) come from the launcher's environment, so this is not yet the per-snapshot venv that module 3 describes. The snapshot must include `engine/`, which `snapshot_kit` already does, but `init` excludes it from the repo copy.
- **`per-snapshot-venv`**: Build a venv for each snapshot from its `requirements.lock`, and run the engine with that venv's interpreter. This is what module 3 describes in full.
  - For: Matches module 3 exactly, including dependency isolation between kits.
  - Against: Needs a lock file in every kit and a venv build on the first run of each snapshot. Larger than this criterion, and it adds a long-lived install step to `snapshot_kit`.

## Why

Not decided. The recommended option gives the criterion a testable behavior: two repos with two stub engines, and the launcher runs each one's engine. It also keeps the run's engine tied to its snapshot, which module 3 requires. The cost is that dependencies are still shared until the venv option is built.

## Source

Written on 2026-11-20 by the session finishing module 16. Module 16's two-kit criterion stays unticked until an option is accepted and built.
