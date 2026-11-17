---
scope: repo
repo: factory
topic: bug-fix-loop-count-3
status: accepted
supersedes: []
---

# Loop count on bug-fix verify to fix

## Decision

Raise the shipped file to max: 3 to match the walkthrough

Chosen option: `raise-to-3`.

## Context

max is the number of loops allowed. bug-fix ships verify->fix with max: 2, so the third failure blocks. The module 8 walkthrough and its sample feedback record say loop 1 of 3 and block on the fourth failure. The code and a test follow the shipped file.

## Options considered

- **`keep-2-fix-doc`** (recommended): Keep max: 2 and change the walkthrough to 2
  - For: No behavior change
  - For: The test pinning the shipped values stays true
  - For: Fewer wasted worker runs before a human is asked
  - Against: Two tries may be too few for a flaky e2e test
  - Against: Changes a decided example in module 8
- **`raise-to-3`** (chosen): Raise the shipped file to max: 3 to match the walkthrough
  - For: The doc and the shipped value agree
  - For: One more chance to fix a failing verify
  - Against: Changes behavior you did not choose
  - Against: More worker cost on a stuck run
  - Against: Needs the pinning test updated

## Why

The page's reason is for the recommended option, which the owner did not choose. The owner's own reason is not recorded.

The shipped value is the one the tests pin, and an example in a walkthrough is the easier thing to change.

## Source

Backfilled on 2026-11-16 from `docs/reviews/wave3-decisions.md`, decision `D2`, page `docs/reviews/wave3-decisions.json`. The owner chose this on 2026-11-15; the answer is the record's, not new.
