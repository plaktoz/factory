---
scope: repo
repo: factory
topic: runspec-script-or-python
status: accepted
supersedes: []
---

# RunSpec shape

## Decision

`script`, `python`, `args`; exactly one of the first two

Chosen option: `script-or-python`.

## Context

TaskSpec has `run: RunSpec | None` and the readiness review lists RunSpec as undefined without proposing a shape. Module 5 shows two forms in the plugin manifest: `run: {script: <path>, args: [...]}` and `run: {python: <module:function>}`.

## Options considered

- **`script-or-python`** (chosen) (recommended): RunSpec has script: str | None, python: str | None, args: list[str]; exactly one of script and python is set
  - For: Matches both forms module 5 already shows
  - For: Small, and checkable by the schema
  - For: The os: rule from module 5 applies to script only
  - Against: A third kind of task, such as a container, needs a new field
- **`tagged-union`**: RunSpec is a tagged union with a kind field: script, python
  - For: Adding a kind later is a new variant, not a new field
  - Against: Changes the YAML in module 5 to add kind: script
  - Against: More ceremony for two kinds

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

It freezes exactly what the spec already writes and changes no example.

## Source

Backfilled on 2026-11-16 from `docs/reviews/open-decisions.md`, decision `Q4`, page `docs/reviews/open-items.json`. The owner chose this on 2026-11-14; the answer is the record's, not new.
