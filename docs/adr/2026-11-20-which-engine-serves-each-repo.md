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

## Follow-up decisions

Accepted by the owner on 2026-11-21, on page `docs/decision-pages/which-engine-open-items.json`, each with the recommended option. They settle build choices this ADR left open. None of them changes the decision above. Each entry lists the options that were not chosen, so this record stands without the page.

- **Follow-up decision `D1` (test files in each repo's engine copy): option `engine-without-tests`.** `init` and `upgrade` copy the engine without its `tests/` folder: 60 files and 0.6 MB, not 128 files and 1.1 MB (counted in bytes, with caches and the local environment left out). The rule is for `factory/engine/tests` only. `factory/launcher/tests` is copied today and stays. Nobody can run the engine's tests from inside a target repo; they run in the factory repo.
  - Not chosen, `engine-with-tests`: copy the whole engine folder. One fewer rule, but 68 extra files (0.5 MB) in every repo and every saved run copy, committed into repos that never run them.
- **Follow-up decision `D2` (a run whose saved kit has no engine): option `refuse-with-fix`.** When a run's `kits/<kit_hash>/factory/engine` folder is missing, the launcher starts nothing and fails with `kit.no_engine` (kind `fail_fast`, exit 2). The message names the run and the kit and says to add `--installed-engine`, a launcher option that runs that one command on the installed engine. Without it the launcher never falls back to the installed engine. `abort` is dispatched like every other run command, so a stuck run is cleared with `factory abort <run> --installed-engine`; the page did not say this, and it was found while applying the decision. A tick that meets such a run records the error in its report and goes on to the next run. No saved kit exists on the owner's machine (`~/.factory/kits` is missing, checked 2026-11-21), so no run is affected now.
  - Not chosen, `fall-back-with-warning`: use the installed engine and print a warning. No old run is ever stuck, but a run can cross engine versions without anyone choosing it, which is what saving the kit is meant to stop, and a warning is easy to miss in a tick.
- **Follow-up decision `D3` (pushing the branch): option `push-docs-now`.** `wave4/m16-criteria` is pushed and one pull request is opened against `main` now, not after the engine change is built.
  - Not chosen, `hold-until-built`: push with the build, so one pull request holds the decision and its proof. The decision stays off `main` until then.
  - Not chosen, `keep-local`: push nothing until told to.
  - The page said the pull request would be 26 files. That compared against a stale local copy of `main`. GitHub's `main` already had the earlier commit `af193d1` through pull request #61, so the pull request is 4 commits and 13 files, 3 of them code.

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

The cost is accepted: dependencies stay shared until phase 1b, and every target repo commits a copy of the engine source. Measured on 2026-11-21 with the `KIT_KEEP` exclusion removed and the existing ignore patterns kept, the engine folder is 128 files and 1.1 MB with its `tests/` folder, and 60 files and 0.6 MB without it. The first draft of this ADR said "58 files, 1.4 MB"; that count was not measured. Whether the copy should leave out `tests/` is a build detail for the follow-up task.

## Consequences

- Module 16's two-kit criterion can be ticked once a test drives two repos with different stand-in engines through one launcher. Until that test exists the criterion stays open.
- A launcher upgrade no longer changes the engine of a repo that is already on a kit. `factory upgrade` does.
- Module 3 and shared contracts section 18 describe the venv; each now says the venv is phase 1b and what runs until then.
- The code and config changes are a follow-up task in `docs/tasks.md` (item 17). None of them is built by this ADR.

## Source

Written on 2026-11-20 by the session finishing module 16, and accepted on 2026-11-21. Answered on page `docs/decision-pages/which-engine-serves-each-repo.json`, decision `D1`; the follow-ups on page `docs/decision-pages/which-engine-open-items.json`, decisions `D1`, `D2` and `D3`. Module 16's two-kit criterion stays unticked until the follow-up task is built and tested.
