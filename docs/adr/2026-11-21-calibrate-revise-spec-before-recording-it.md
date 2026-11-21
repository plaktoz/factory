---
scope: repo
repo: factory
topic: calibrate-revise-spec-before-recording-it
status: accepted
supersedes: []
---

# revise-spec is calibrated before its decisions are recorded

## Decision

Accepted by the owner on 2026-11-21, on page `.scratch/issue-55-revise-spec.json`, decision `D7`: option `calibrate-then-adr`, the recommended option.

The order of work was: write the skill, score the calibration files, adjust the rules, save the results, then write the ADRs citing them. The ADRs for decisions D1 to D8 were written after the calibration runs finished, so they cite measured results.

## Context

An accepted ADR cannot be edited, only superseded. On 2026-11-21 calibration found that the first draft of the rules scored every design file at 3 on at least two dimensions. That led to three changes, made before any ADR was written: design docs are no longer scored on rejected options, a tie names every tied dimension, and a backfilled ADR is scored on its own text. Had the ADRs been written first, they would have recorded the first draft's rules.

## Options considered

- **`calibrate-then-adr` (chosen, recommended).** Calibrate, adjust, then record.
  - For: the ADRs record tested numbers. No superseding ADR is needed if the rules turn out wrong.
  - Against: the decision is on record later, and the calibration run is the first real cost of the skill.
- **`adr-then-calibrate` (not chosen).** Record now, test later.
  - For: the decision is on record at once.
  - Against: a change to the rules would need a superseding ADR, and the record would hold untested numbers.
- **`skip-calibration` (not chosen).** Ship with the issue's anchors untried.
  - For: the fastest.
  - Against: nobody knows whether a good file scores well, and it gives up the main protection against inconsistent scoring.

## Why

Trying the rubric on real files first avoided recording rules that had to change within the hour.

## Consequences

- The calibration changed the rules, which shows the step was worth its cost. It did not reach its target: the strong files did not score 4 or higher, and the owner chose to record that as a baseline. See `2026-11-21-calibrate-revise-spec-on-real-files`.
- The rules may still change. A change after this point is a new ADR that supersedes the one it changes.

## Source

Written on 2026-11-21 by Claude Code from the owner's answer on `.scratch/issue-55-revise-spec.json`, decision `D7`. The answer is the owner's, not new.
