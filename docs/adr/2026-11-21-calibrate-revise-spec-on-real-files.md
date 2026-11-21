---
scope: repo
repo: factory
topic: calibrate-revise-spec-on-real-files
status: accepted
supersedes: []
---

# revise-spec is calibrated on real files from this repo

## Decision

Accepted by the owner on 2026-11-21, on page `.scratch/issue-55-revise-spec.json`, decision `D6`: option `four-real-files`, the recommended option.

The skill is calibrated on real files, not invented examples. The set the page named:

- `docs/design/modules/17-housekeeping.md`, expected strong.
- `docs/design/modules/05-workflows-and-plugins.md`, expected weak.
- `docs/adr/2026-11-17-wire-commands-next.md`, expected strong.
- `docs/adr/2026-11-14-cmd-task-non-zero-exit-is-a-check-failure.md`, expected weak.

Accepted ADRs are used only as examples and are never edited.

One file was added during the work: `docs/design/modules/14-token-tracking.md`, as a second candidate for a strong design file after module 17 scored lower than expected. The five scored files and both runs of each are in `.claude/skills/revise-spec/references/calibration-2026-11-21.md`.

## Context

Checked on 2026-11-21: no `proposed` ADR exists, so ADR calibration uses accepted files. Module 17 has 10 of 10 criteria ticked and module 5 has 4 ticked and 6 open (`criteria.py`). The labels "strong" and "weak" came from those counts and a read of the files, not from a score.

## Options considered

- **`four-real-files` (chosen, recommended).** Two design files and two accepted ADRs.
  - For: the examples match how this repo writes, both variants are covered, and a weak case shows what the rubric should catch.
  - Against: accepted ADRs differ from proposed ones. The weak design file's gaps are partly phase 1b work.
- **`design-only` (not chosen).** Two design files, ADR variant calibrated later.
  - For: fewer files to keep up to date.
  - Against: the ADR scoring would ship untested, and the wait could be long because no proposed ADR exists.
- **`invented-examples` (not chosen).** Made-up specs with chosen scores, as the issue suggested.
  - For: full control over what each example shows.
  - Against: invented files do not look like the repo's, so calibration drifts, and they are more to keep.

## Why

Real files teach the scorer what this repo's good and weak specs look like.

## Consequences

- The results did not match the labels. Module 17 and the first run of the strong ADR scored lower than expected. Module 17's gaps were checked against the file and are real, so the label was wrong, not the rubric. No design file reached `ready`.
- The calibration is a baseline, not a pass. The owner chose to record the results and turn the spec gaps in modules 5, 14 and 17 into tasks, not to edit those files here.
- Not built: a repeat measurement of the strong ADR, and a proposed ADR as a calibration case once one exists.

## Source

Written on 2026-11-21 by Claude Code from the owner's answer on `.scratch/issue-55-revise-spec.json`, decision `D6`, and the owner's later choice to record the calibration as the baseline. The answer is the owner's, not new.
