---
scope: repo
repo: factory
topic: strict-xfail-for-known-gaps
status: accepted
supersedes: []
---

# Strict xfail closes an expected failure

## Decision

The rebuild test used strict xfail: the marker was kept until the fix and removed in the same change. A criterion that fails for a known gap is marked `xfail(strict=True)` with the gap named in the reason, and the marker is removed in the change that closes the gap.

Chosen option: `strict-xfail`, for both Q1 and Q2.

## Context

The rebuild criterion of module 6A was an expected failure, marked strict, until E1 landed (see [rebuild-run-from-last-snapshot](2026-11-15-rebuild-run-from-last-snapshot.md)). Once E1 landed, the test passed and the marker had to be removed in the same change. E2 on `rebuild-run-decisions` asked how that expected failure is closed and had no recorded answer. Page `e2-expected-failure` (`docs/reviews/e2-expected-failure.json`) asked it as two questions:

- **Q1** What the record says happened to the rebuild test.
- **Q2** The rule for the next known gap.

Checked with pytest 9.2.0: a strict xfail that passes fails the suite with `XPASS(strict)`, a strict xfail that still fails shows as `XFAIL`, and a skipped test is not run and shows as `SKIPPED`. The repo uses `skip` or `skipif` only for missing tools (Chrome, `srt`, `npm`, `uv`, a live-run switch).

## Options considered

Both questions had the same two options.

- **`strict-xfail`** (chosen) (recommended): Q1 records that the marker was kept until the fix and removed in the same change. Q2 marks the failing criterion `xfail(strict=True)` with the gap named in the reason, and removes the marker in the change that closes it.
  - For: A fix that changes the result is noticed at once, because the suite fails with `XPASS(strict)` until the marker is removed
  - For: The gap shows as `XFAIL` in every run until it is closed
  - For: A skip in this repo keeps one meaning, a missing tool
  - For: The record describes what the repo did
  - Against: The author of the fix must remove the marker, or the suite fails
  - Against: If the test fails for a different reason than the named gap, it still shows as `XFAIL` and the new failure is hidden
  - Against: For the rebuild test the case is finished, so Q1 changes no behavior
- **`skip`**: Q1 records a skip until the fix. Q2 marks the criterion `skip` with the gap named in the reason.
  - For: Nothing fails and nothing shows as failing while the gap is open
  - For: No one is forced to touch the marker when a fix lands
  - Against: The test does not run, so a fix that makes it pass goes unnoticed and the skip can stay for ever
  - Against: The gap shows only as one line in the `SKIPPED` summary, next to the skips for missing tools
  - Against: A criterion is ticked only with test evidence, and a skipped test gives none

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

A strict xfail keeps the test running and forces the marker out with the fix; a skip does neither.

## Source

Answered on 2026-11-16 on page `docs/reviews/e2-expected-failure.json`, decision `Q1` and decision `Q2`. Q1 also answers decision `E2` on page `docs/reviews/rebuild-run-decisions.json`, which asked how the rebuild test's expected failure is closed. The owner chose `strict-xfail` for both; the answer is the record's, not new. The owner accepted this ADR in the session, as AGENTS.md requires.
