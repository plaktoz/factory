# Factory

A reusable software factory: a deterministic Python engine that turns a request into reviewed work, with LLM workers doing bounded tasks. The spec is `docs/design/phase-1.md`, an overview that links one file per module under `docs/design/modules/` and the cross-cutting sections under `docs/design/shared/`. Read the module's file, its contract and its acceptance criteria, before touching a module.

## Layout

| Path | What | Spec module |
| --- | --- | --- |
| `factory/engine/factory_engine/` | Engine package. One file per contract, named in [shared contracts](docs/design/shared/18-shared-contracts.md). | 3 to 14, 17, 17A |
| `factory/engine/factory_engine/adapters/{tracker,worker}/` | File/GitHub trackers, Claude/command/fake workers | 7, 9 |
| `factory/engine/tests/<module>/` | Tests named in each module's "Run and test" line | all |
| `factory/engine/tests/contracts/` | Checks that public signatures match the spec | 20 |
| `factory/launcher/` | Machine launcher, `tick`, dashboard server | 15, 16 |
| `factory/dashboard/` | The dashboard page: plain HTML in 1a, prebuilt React bundle in 1b (no React source exists yet) | 15 |
| `factory/{workflows,schemas,policies,languages,shims}/` | Shipped data the engine loads | 5, 17A |
| `factory/skills/own/` | The factory's own skills, including `practices/` | 10 |
| `docs/` | See `docs/README.md` | - |
| `scripts/docs-check/` | Checks on the spec: links, Mermaid blocks, module contracts. See its README | - |

`factory/` is the kit that gets copied into other repos, so nothing in it may reference this repo's `docs/`. The two paths `docs/adr` and `docs/research` in `delivery.py` are not references: they name folders in the target repo where a run's deliverables go (modules 7 and 13). `.factory/` is created by `factory init` and is not committed here.

## Building one module

1. Open `docs/design/modules/<NN>-<name>.md`. Its title block gives the build wave.
2. Read the *Module contract* (depends on, writes, CLI it backs, function signatures), then the *Acceptance criteria*.
3. Code against fakes of the modules it depends on (`FakeWorkerAdapter`, `FakeTracker`, `FakePullRequests`, `FakeClock`).
4. Done when every acceptance criterion in that file has a passing test and the public functions match the contract signatures.
5. Change the module's file in the same commit as the code that changes its behavior.

## Rules

- Module dependencies follow [the dependency map](docs/design/shared/20-dependencies-and-plan.md). No module imports `engine.py` or `api.py`; only drivers compose modules.
- Only the process holding a run's lock writes `run.json` and `task.json`.
- Every state file has a JSON Schema in `factory/schemas/`. The dataclasses mirror it.
- Code against fakes of upstream modules, not the real ones, until the wave they belong to lands.

## Build order

Build phase 1a first (walking skeleton: Claude only, bug-fix and chore, macOS and Linux, read-only dashboard). Phase 1b adds the other workflows, plugins, MCP, practice packs and dashboard writes. The table is in spec section 1, "Phase split". Phase 2 items (Codex, Windows, answering by GitHub comment) are in `docs/design/phase-2.md`; do not build them in phase 1. Decisions already made are in `docs/reviews/phase-1-decisions.md`; do not reopen them without a new ADR.


Wave 0 (shared types, schemas, fakes) first. Then wave 1: 3, 6A, 7, 10, 14, 17A. Then wave 2: 4, 5, 8, 9, 11, 12, 17. Then wave 3: 13, 6B, 15. Then 16. See [the plan](docs/design/shared/20-dependencies-and-plan.md).
