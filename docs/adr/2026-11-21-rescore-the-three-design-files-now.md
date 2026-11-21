---
scope: repo
repo: factory
topic: rescore-the-three-design-files-now
status: accepted
supersedes: []
---

# Modules 5, 14 and 17 are re-scored now, not later and not dropped

## Decision

Accepted by the owner on 2026-11-21, on the page "Open items after the issue 55 follow-ups" (`.scratch/open-owner-items.json`, since deleted; its answers are in these records), decision `D1`: option `rescore-now`, the recommended option.

Each of the three files was scored once more by a fresh sub-agent that read only `.claude/skills/revise-spec/SKILL.md` and the file. The three scorecards are in `.claude/skills/revise-spec/references/calibration-2026-11-21.md` as run 3. The `ready` target of task 33 stays, and it is still not met.

## Context

Task 33 asked for a design file to reach `ready`. The baseline gave `needs-changes` for modules 5, 14 and 17, and the gaps it found were edited into the spec (`2026-11-21-fix-design-gaps-the-scorecards-found`, commit `6a69067`) but not scored again.

Result of run 3, checked by running the scorers and then reading the lines they quoted in the files:

| File | Scope | Soundness | Failure | Buildability | Recommendation |
| --- | --- | --- | --- | --- | --- |
| module 5 | 4 | 3 | 4 | 3 | needs-changes |
| module 14 | 4 | 4 | 4 | 3 | needs-changes |
| module 17 | 4 | 3 | 4 | 3 | needs-changes |

Against run 2, module 5 gained a point on Scope and on Failure, module 14 gained a point on Soundness and on Failure, and module 17 did not move. Every scorer's headline gap that I looked up is in the file: module 17 L99 still says "This is a possible bug" against the L53 rule, module 17 L128 still has the `worker.log` criterion unticked, and module 5 L281 still says a task has "both or neither of skill and cmd" while plugin tasks may have only `run`. Module 6 has no `usage_unreadable` entry, which the module 14 scorer reported.

## Options considered

- **`rescore-now`** (chosen, recommended): three fresh scorecards now.
  - For: it tells the owner whether the D2 fixes worked, and it is advice only, so nothing is undone if it is wrong.
  - Against: a score can move by a point with no change to the file, so one run per file is weak proof.
- **`drop-target`** (not chosen): close task 33 and say the `ready` goal is dropped.
  - For: no more time on scoring.
  - Against: nobody learns whether the fixes helped, and the skill stays untested on a passing file.
- **`rescore-later`** (not chosen): wait until the pilot tickets end.
  - For: real tickets add evidence.
  - Against: the pilot has no start day yet (task 18), and task 33 would stay open with nothing driving it.

## Why

A re-score is cheap and reversible, and it is the only way to find out whether the fixes worked.

## Consequences

- **No file reached `ready`.** Task 33 stays `[ ]`. Its new reason is the list of remaining gaps in the calibration reference, run 3.
- **Not built:** the fixes for those gaps. They are spec edits to modules 5, 14, 17, 6 and 9, and no ADR or task has chosen to make them. Task 33 now says so.
- **Noise:** one run per file does not measure spread. The strong ADR was run five times for that (`2026-11-21-rerun-the-three-missing-scorecards`).
- **Task:** `docs/tasks.md` item 33.

## Source

Written 2026-11-21 by the Claude Code session that applied the owner's answer (run `d5c2b949-b212-4992-9a5c-6284ed60de53`), from the page `.scratch/open-owner-items.json`, decision `D1`.
