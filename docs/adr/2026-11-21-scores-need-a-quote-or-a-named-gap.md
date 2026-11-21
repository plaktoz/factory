---
scope: repo
repo: factory
topic: scores-need-a-quote-or-a-named-gap
status: accepted
supersedes: []
---

# Every revise-spec score needs a quoted line or a named gap, and thin evidence scores lower

## Decision

Accepted by the owner on 2026-11-21, on page `.scratch/issue-55-revise-spec.json`, decision `D4`: option `quote-and-name-gap`, the recommended option.

In the `revise-spec` skill, a score of 4 or 5 must quote the line that shows the property, with its line number. A score of 3 or less must name the specific missing item and the line where it belongs. When the evidence is thin, or the scorer cannot choose between two scores, the lower one is given. A score with no evidence line is invalid and is redone.

## Context

A model scores the same text differently between runs. Measured on 2026-11-21: the same ADR (`2026-11-17-wire-commands-next.md`) got Consequences 3 on one run and 4 on the next, and the first run's recommendation was `needs-changes` where the second's was `ready`. Between those runs the rules had changed in three places, so this is not a clean repeat (see `.claude/skills/revise-spec/references/calibration-2026-11-21.md`). Scorers also had to guess where a missing item has no line to quote, and the skill now says to cite where it belongs.

## Options considered

- **`quote-and-name-gap` (chosen, recommended).** Quote for 4 and 5, name the gap for 3 or less, score down when unsure.
  - For: a reader can check any score by reading one line. Scores drift less because the evidence is tied to text. It costs one run.
  - Against: it does not remove variance, since two runs can pick different lines. It pushes scores down, so some good files read as `needs-changes` at first.
- **`takeaway-only` (not chosen).** A score and a one-line remark, no required quote.
  - For: the shortest scorecard.
  - Against: a score cannot be checked without redoing the review, which leaves the inconsistency the issue set out to fix.
- **`median-of-three` (not chosen).** Score three times and report the middle result.
  - For: it smooths one-off swings.
  - Against: it triples the cost of every run, and three runs can share one blind spot, so steadier is not the same as right.

## Why

Evidence a reader can check is the cheapest way to make a model's score trustworthy.

## Consequences

- The rule does not remove the spread seen on the strong ADR. The calibration record lists a repeat measurement as open work. Not built here: a repeat run, and a Consequences anchor that says whether option costs count.
- Expect lower scores than a reviewer would give by feel, because thin evidence scores down.

## Source

Written on 2026-11-21 by Claude Code from the owner's answer on `.scratch/issue-55-revise-spec.json`, decision `D4`. The answer is the owner's, not new.
