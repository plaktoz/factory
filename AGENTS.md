# Factory

A reusable software factory: a deterministic Python engine that turns a request into reviewed work, with LLM workers doing bounded tasks. The spec is `docs/design/phase-1.md`. Read the module contract before touching a module.

## Layout

| Path | What | Spec module |
| --- | --- | --- |
| `factory/engine/factory_engine/` | Engine package. One file per contract, named in spec section 18. | 3 to 14, 17, 17A |
| `factory/engine/factory_engine/adapters/{tracker,worker}/` | File/GitHub trackers, Claude/Codex/command/fake workers | 7, 9 |
| `factory/engine/tests/<module>/` | Tests named in each module's "Run and test" line | all |
| `factory/engine/tests/contracts/` | Checks that public signatures match the spec | 20 |
| `factory/launcher/` | Machine launcher, `tick`, dashboard server | 15, 16 |
| `factory/dashboard/` | Prebuilt React bundle (source lives elsewhere until built) | 15 |
| `factory/{workflows,schemas,policies,languages,shims}/` | Shipped data the engine loads | 5, 17A |
| `factory/skills/own/` | The factory's own skills, including `practices/` | 10 |
| `docs/` | See `docs/README.md` | - |

`factory/` is the kit that gets copied into other repos, so nothing in it may reference this repo's `docs/`. `.factory/` is created by `factory init` and is not committed here.

## Rules

- Module dependencies follow spec section 20. No module imports `engine.py` or `api.py`; only drivers compose modules.
- Only the process holding a run's lock writes `run.json` and `task.json`.
- Every state file has a JSON Schema in `factory/schemas/`. The dataclasses mirror it.
- Code against fakes of upstream modules, not the real ones, until the wave they belong to lands.

## Build order

Build phase 1a first (walking skeleton: Claude only, bug-fix and chore, macOS and Linux, read-only dashboard). Phase 1b adds Codex, the other workflows, plugins, MCP, practice packs and dashboard writes. The table is in spec section 1, "Phase split". Decisions already made are in `docs/reviews/phase-1-decisions.md`; do not reopen them without a new ADR.


Wave 0 (shared types, schemas, fakes) first. Then wave 1: 3, 6A, 7, 10, 14, 17A. Then wave 2: 4, 5, 8, 9, 11, 12, 17. Then wave 3: 13, 6B, 15. Then 16. See spec section 20.
