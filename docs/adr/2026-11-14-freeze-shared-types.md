---
scope: repo
repo: factory
topic: freeze-shared-types
status: accepted
supersedes: []
---

# Which shared types wave 0 freezes

## Decision

freeze the 20 shared types now, with the shapes proposed in the readiness review (`docs/reviews/ready-for-development.md`), in section 18

Chosen option: `freeze-shared`.

## Context

47 names used in signatures are defined nowhere. 15 of them cross a module boundary (GateSpec and GateContext are used by seven modules), and 5 more shared types appear only in field lists. A type that two modules build to different shapes fails when they meet.

## Options considered

- **`freeze-shared`** (chosen) (recommended): Freeze the 20 shared types now, with the shapes proposed in the review, and put them in section 18
  - For: Every module in waves 1 to 3 codes to one shape
  - For: The shapes come from how callers already use each type, and the contract tests (W0.6) check them
  - For: The fakes can be written in wave 0
  - Against: Some shapes may be wrong until a module uses them; a change then touches every caller
  - Against: About 28 module-local types still wait for their own wave
- **`freeze-core`**: Freeze only the types section 18 already lists, plus Clock; each module defines the rest in its own wave
  - For: Less written before any code exists
  - For: Each owner shapes its own types with its tests in hand
  - Against: The gap review shows the cross-module types (GateContext, PrRef, JoinResult) are the ones that mismatch
  - Against: The fakes in wave 0 need those types, so they would be written against guesses

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

The types that cross modules are exactly where parallel builds fail, so fixing them first costs less than reconciling them later.

## Source

Backfilled on 2026-11-16 from `docs/reviews/open-decisions.md`, decision `R1`, page `docs/reviews/open-decisions.json`. The owner chose this on 2026-11-14; the answer is the record's, not new.
