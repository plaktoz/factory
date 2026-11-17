---
scope: repo
repo: factory
topic: one-config-type
status: accepted
supersedes: []
---

# One configuration type or two

## Decision

one `Config` with a machine part and a repo part; `tick` takes a `Config` loaded with `repo=None`

Chosen option: `one-config`.

## Context

Module 3 defines `load_config(repo) -> Config` and merges machine and repo files into it. Module 16 calls `tick(cfg: MachineConfig, ...)`, and no module defines `MachineConfig`. `tick` runs with no repo, so `repo=None` is already allowed.

## Options considered

- **`one-config`** (chosen) (recommended): One Config with a machine part and a repo part; `tick` takes a Config loaded with repo=None
  - For: No new type or loader
  - For: Precedence (flag, env, machine, repo, default) stays in one place
  - For: Matches module 3 as written; only module 16's signature changes
  - Against: A function that needs only machine settings can still be handed repo fields
- **`two-configs`**: Keep MachineConfig as its own type, with `load_machine_config` added to module 3
  - For: The type says which settings a function may read
  - For: `tick` cannot read a repo setting by mistake
  - Against: A second loader, schema and set of tests
  - Against: Functions that need both take two arguments

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

Module 3 already merges both files into one Config, so one type needs no new code.

## Source

Backfilled on 2026-11-16 from `docs/reviews/open-decisions.md`, decision `R2`, page `docs/reviews/open-decisions.json`. The owner chose this on 2026-11-14; the answer is the record's, not new.
