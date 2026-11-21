---
scope: repo
repo: factory
topic: measure-the-scoring-spread-on-the-strong-adr
status: accepted
supersedes: []
---

# The scoring spread on the strong ADR is measured with repeat runs

## Decision

Accepted by the owner on 2026-11-21, on the follow-up page for issue 55 (`.scratch/issue-55-follow-ups.json`, since deleted; its answers are in these records), decision `D3`: option `measure-three-runs`, the recommended option.

The strong ADR (`2026-11-17-wire-commands-next`) was scored three more times on unchanged rules. The session handoff reports five runs in all: `needs-changes` on 4 of the 5, with Options and Consequences each moving between 3 and 4. The handoff is the only source for the three new scores (see Consequences).

## Context

The first two runs, recorded in `.claude/skills/revise-spec/references/calibration-2026-11-21.md`, gave Consequences 3 then 4, and the recommendation flipped from `needs-changes` to `ready`. One flipped recommendation was the reason to measure before anyone relied on a score (task 28).

## Options considered

- **`measure-three-runs` (chosen, recommended).** Three more scorecards on the same file.
  - For: turns a guess about noise into a number.
  - Against: three runs show a spread but cannot prove stability.
- **`accept-one-point` (not chosen).** Close the task and treat a one-point spread as normal.
- **`tighten-then-measure` (not chosen).** Add a sentence to the Consequences anchor first, then measure.

## Why

Measuring on unchanged rules shows the spread of the rules as they stand, and costs three runs.

## Consequences

- The spread is one point on Options and Consequences, but the recommendation is not stable: it was `ready` on one run in five. A `ready` from one run is not evidence.
- **Not recorded in the repo:** the calibration reference holds only the first two runs. The three added scorecards are not written there, so the 4 of 5 figure rests on the session handoff. Task 28's follow-up stays unticked until they are recorded.
- No rule changed because of this result. The Consequences anchor still does not say whether costs listed under an option count; that is the cause the scorer named, and it is still open.

## Source

Written on 2026-11-21 by Claude Code from the owner's answer on the follow-up page for issue 55 (`.scratch/issue-55-follow-ups.json`, since deleted; its answers are in these records), decision `D3`, and the session handoff of 2026-11-21, which reported the five runs. The answer is the owner's, not new.
