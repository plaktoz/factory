---
scope: repo
repo: factory
topic: accept-draft-report-schemas
status: accepted
supersedes: []
---

# Draft report schemas and merge.json

## Decision

Accept the drafts as the phase 1 schemas

Chosen option: `accept-drafts`.

## Context

The spec gave no fields for stage-report, test-report, source-notes and review-findings, so wave 3 shipped drafts marked x-status: draft. merge.json (module 13) has no schema and is written as auto, reason and rules[{rule, passed, detail}]. The bug-fix gates run on these today. A finding of medium or high severity blocks, which matches review_findings_at_or_above: medium in module 13.

## Options considered

- **`accept-drafts`** (chosen) (recommended): Accept the drafts as the phase 1 schemas
  - For: bug-fix runs now with no change
  - For: The shapes are the smallest the skills and gates need
  - For: Changing a field later is a schema edit plus tests
  - Against: Real model output may not fit; there has been no live run
  - Against: Each draft's x-status and DRAFT text must be removed by hand
- **`accept-after-live-run`**: Keep them as drafts until the first live run, then freeze
  - For: Fields come from real artifacts, not guesses
  - For: No premature freeze
  - Against: The drafts stay unsettled during the tutorial test
  - Against: Needs a live run, which needs 6B and 16
- **`write-merge-schema`**: Accept the drafts and also write a merge schema now
  - For: merge.json is validated like every other state file
  - For: The dashboard can reject a bad merge.json
  - Against: Fixes the guessed merge.json fields into a schema before module 15 reads them for real
  - Against: More files to keep in sync with module 13

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

The drafts are the smallest shape that makes bug-fix run, and a live run will show whether any field is wrong.

## Source

Backfilled on 2026-11-16 from `docs/reviews/wave3-decisions.md`, decision `D1`, page `docs/reviews/wave3-decisions.json`. The owner chose this on 2026-11-15; the answer is the record's, not new.
