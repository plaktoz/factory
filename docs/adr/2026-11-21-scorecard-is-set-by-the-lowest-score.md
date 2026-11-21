---
scope: repo
repo: factory
topic: scorecard-is-set-by-the-lowest-score
status: accepted
supersedes: []
---

# The scorecard is one block, and its recommendation is set by the lowest score

## Decision

Accepted by the owner on 2026-11-21, on page `.scratch/issue-55-revise-spec.json`, decision `D2`: option `lowest-score-block`, the recommended option.

The `revise-spec` skill scores each dimension from 1 to 5 in whole numbers and writes one block. The recommendation follows the lowest score:

- `ready`: every dimension is 4 or more.
- `needs-changes`: the lowest is 3.
- `rework`: the lowest is 2 or less.

There are no weights and no overall number. If dimensions tie at the lowest score, the block names every one of them. Each score cites a line. The block lists one blocking item per dimension at 3 or less. The skill writes it to the screen or a file the user names and never edits the file it scores.

## Context

The issue proposed weights of 25, 30, 25 and 20, a 4.0 overall bar and a 3.0 floor per category. Checked by arithmetic on 2026-11-21: scores of 5, 5, 3, 3 give 1.25 + 1.50 + 0.75 + 0.60 = 4.10, which passes, while the issue's own anchor for a 3 is "needs revision". The issue's example scorecard also shows a 4.5, which the whole-number anchors do not define.

The glossary in `docs/design/phase-1.md` reserves "Gate" for a deterministic check and "Approval" for a human stop. The block therefore says "Recommendation", not "Status: Approved".

## Options considered

- **`lowest-score-block` (chosen, recommended).** One block, recommendation from the lowest score.
  - For: a strong dimension cannot hide a weak one. It is quick to scan and each score points at a line. There is no false precision from a decimal.
  - Against: one 3 caps the result at `needs-changes`, which is harsher than an average. It differs from the layout the issue's author drew, so the issue needs a reply.
- **`weighted-total` (not chosen).** The issue's layout: weights, a total, a status word.
  - For: it matches the issue, and one number is easy to quote.
  - Against: 5, 5, 3, 3 passes at 4.10. A move from 4.1 to 3.9 decides pass or fail on a judgment that varies between runs.
- **`findings-list` (not chosen).** A list of problems with a line and a severity, no scores.
  - For: the same shape as the factory's other reviewers, and no scoring to calibrate.
  - Against: nothing says whether a file is ready, and lists differ from run to run.

## Why

The lowest-score rule removes the issue's own contradiction and keeps a summary a reviewer can scan.

## Consequences

- `ready` is rare. Calibration on 2026-11-21 found no design file at `ready` (see `.claude/skills/revise-spec/references/calibration-2026-11-21.md`). The first pull request that uses the skill will probably get `needs-changes`.
- The factory's `no-blocking-findings` gate reads `review-findings` JSON. A scorecard is a different artifact and no gate reads it. Making it a workflow stage is not built here and needs a mapping to findings and a spec change.
- A reply on issue 55 with this decision is not written by this ADR.

## Source

Written on 2026-11-21 by Claude Code from the owner's answer on `.scratch/issue-55-revise-spec.json`, decision `D2`. The answer is the owner's, not new.
