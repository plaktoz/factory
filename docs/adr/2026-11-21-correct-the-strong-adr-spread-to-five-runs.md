---
scope: repo
repo: factory
topic: correct-the-strong-adr-spread-to-five-runs
status: accepted
supersedes:
  - 2026-11-21-measure-the-scoring-spread-on-the-strong-adr
---

# The strong ADR's scores are five runs, and Options did not move

## Decision

Accepted by the owner on 2026-11-21, on the page "Open items after the issue 55 follow-ups" (`.scratch/open-owner-items.json`, since deleted; its answers are in these records), decision `D5`: option `rerun-three`. The owner chose it over the recommended option, `write-superseding-adr`. The earlier ADR `2026-11-21-measure-the-scoring-spread-on-the-strong-adr` is superseded for its claims about the runs. Its decision to measure is unchanged.

Five runs of the strong ADR (`2026-11-17-wire-commands-next`) are now on file in `.claude/skills/revise-spec/references/calibration-2026-11-21.md`, each by a fresh sub-agent given only `SKILL.md` and the file.

## Context

The superseded ADR said the scores came from a handoff note: "`needs-changes` on 4 of the 5 runs, with Options and Consequences each moving between 3 and 4." Two runs were on file, and the other three were not.

The three missing runs were made on 2026-11-21 (runs 3, 4 and 5, under the same rules; each scorer was given only `SKILL.md` and the file). Five runs in all:

| Run | Options | Justified | Consequences | Recommendation |
| --- | --- | --- | --- | --- |
| 1 | 4 | 4 | 3 | needs-changes |
| 2 | 4 | 4 | 4 | ready |
| 3 | 4 | 3 | 3 | needs-changes |
| 4 | 4 | 3 | 3 | needs-changes |
| 5 | 4 | 4 | 3 | needs-changes |

What the five runs show:

- `needs-changes` on 4 of the 5 runs: the old claim holds.
- Options is 4 in all five. The old "Options ... moving between 3 and 4" is wrong; Options did not move.
- Consequences moved between 3 and 4 (4 in run 2 only). That part of the old claim holds.
- Justified moved between 3 and 4 (3 in runs 3 and 4). The old ADR did not mention it.
- Run 2 is the only `ready`.

The scorers' gap claims for the strong ADR were not checked against the file. Only their scores are recorded here.

## Options considered

- **`rerun-three`** (chosen by the owner): run the three missing scorecards again, and record them.
  - For: the record now matches what can be shown, and the spread has real data.
  - Against: the old handoff figures do not match the new runs, so the old ADR needed a correction.
- **`write-superseding-adr`** (the recommended option, not chosen): write only a correction that says two runs are on file.
  - For: the smallest change, and it says only what was on file.
  - Against: leaves the noise unmeasured, which is why the spread was to be measured.
- **`paste-scorecards`** (not chosen): paste the three scorecards from the earlier session.
  - For: keeps the first measurement as it was.
  - Against: the earlier scorecards could not be found, so this could not be done.

## Why

The owner chose to run the scorecards again, so the spread has a measured basis. Five runs are the record now, and the old ADR's counts are corrected from them.

## Consequences

- **The earlier ADR is superseded** for its claims about the runs. Its decision to measure stays.
- **Task 28's numeric check holds:** across the five runs no score moved by more than one point (Consequences and Justified, 3 to 4). The recommendation changed on one run in five, so a `ready` from one run is still not evidence.
- **Task 28's remaining `[ ]`** is the Consequences anchor: whether costs listed under an option count as consequences. The scorers named this as the cause of the run 1 to run 2 flip. Changing the anchor is a change to `SKILL.md`, and it is not built; it needs its own decision.
- **Task:** `docs/tasks.md` item 28 and the Log.

## Source

Written 2026-11-21 by the Claude Code session that applied the owner's answer (run `d5c2b949-b212-4992-9a5c-6284ed60de53`), from the page `.scratch/open-owner-items.json`, decision `D5`.
