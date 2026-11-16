---
scope: repo
repo: factory
topic: spec-layout
status: accepted
supersedes: []
---

# One spec file per module

## Decision

The phase 1 spec is split by the sections it already had. `docs/design/phase-1.md` keeps the overview, the decisions made, the glossary, the module map and the phase split. Each module has its own file under `docs/design/modules/`, and the cross-cutting sections are under `docs/design/shared/`. The main file links every one of them.

## Why

- Size: the single file was 2,706 lines. A person or an agent building one module had to load all of it to read one contract.
- Ownership: each module already had its own contract, tests and acceptance criteria, and in wave 1 to 3 different people build them in parallel. One file per module gives each builder one place to work and keeps their diffs apart.
- Review: a change to one module is a small diff in one file, and `git log` on the file shows that module's history.

## Layout

| Path | Holds |
| --- | --- |
| `phase-1.md` | Overview, principles, decisions made, module map, shared sections index, phase split, glossary |
| `modules/NN-name.md` | One module: what it owns, rules, contract, tests, errors, acceptance criteria. 6A and 6B stay together in `06-engine-core.md` because they share one state model |
| `shared/` | 18 shared contracts, 19 error handling types, 20 dependencies and plan, 21 decisions and sources, and the operator walkthrough |
| `phase-2.md` | Items moved out of phase 1 |

## Rules

- Module numbers do not change. A new module takes the next free number or a letter suffix, such as 17A.
- Cross-references use links to the file, not "section N" or line numbers. Module 20's dependency map remains the single list of who depends on whom.
- A fact lives in one file. Other files link to it.

## Consequences

- A module file shows its build wave under its title, so the order is visible without opening module 20.
- Scripts that read the whole spec read `phase-1.md` and the files under `modules/` and `shared/`.
