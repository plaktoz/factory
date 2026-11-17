---
scope: repo
repo: factory
topic: record-the-model-the-harness-reports
status: accepted
supersedes: []
---

# Which model the engine records for this repo

## Decision

Leave `model` unset; store the models the harness result reports

Chosen option: `observed`.

## Context

Workers must not send a model override here. The usage record still needs a model name, and the gateway reports one at run time (this session's own calls report an unrecognized model name).

## Options considered

- **`observed`** (chosen) (recommended): Leave model unset, and store whatever the harness result reports as the observed model
  - For: Honest record of what ran
  - For: No override sent
  - For: Works if the gateway changes model
  - Against: The name may be an alias such as an internal gateway label
  - Against: Reports group by an unstable string
- **`label`**: Store a fixed label from repo config, such as 'gateway-default'
  - For: Stable grouping in reports
  - For: Simple
  - Against: Can silently hide a real model change
  - Against: A guess recorded as a fact

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

The usage record is for facts, so it keeps what the harness reported.

## Source

Backfilled on 2026-11-16 from `docs/reviews/phase-1-decisions.md`, decision `P4`, page `docs/reviews/pilot-repo-decisions.json`. The owner chose this on 2026-11-14; the answer is the record's, not new.
