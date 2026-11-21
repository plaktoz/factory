---
scope: repo
repo: factory
topic: split-calibration-task-baseline-and-target
status: accepted
supersedes: []
---

# The calibration task is split into a done baseline and an open target

## Decision

Accepted by the owner on 2026-11-21, on page `.scratch/issue-55-follow-ups.json`, decision `D1`: option `split-baseline-and-target`, the recommended option. The page called it "Split it: baseline done, target open".

`docs/tasks.md` item 23 stays ticked and now says only what was done: the calibration baseline was recorded for five files. The target that no design file reached `ready` is a separate unticked item, 26, which stays open until a design file reaches `ready` or the owner drops the target.

## Context

Checked on 2026-11-21 by reading `docs/tasks.md` and `.claude/skills/revise-spec/references/calibration-2026-11-21.md`. Item 23 was ticked and its own text said "the strong files did not reach `ready`, so the target is not met". A ticked item that says its target failed shows two things at once, and a reader can take either one. The calibration record shows that no design file scored `ready` on either run: modules 17, 14 and 5 all scored `needs-changes`, and the strong ADR scored `needs-changes` on one run and `ready` on the next.

## Options considered

- **`split-baseline-and-target` (chosen, recommended).** Item 23 is ticked for the baseline. Item 26 is unticked for the target.
  - For: each line says one true thing. The unmet target stays visible. It matches the owner's choice to record the baseline now.
  - Against: one more item in a long list. The target may never close if nobody fixes the files.
- **`reopen-23` (not chosen).** Untick item 23 until a file reaches `ready`.
  - For: nothing is marked done that is not done.
  - Against: the baseline the owner approved looks unfinished, and the item waits on spec edits that need their own approval.
- **`drop-the-target` (not chosen).** Keep item 23 ticked and remove the target from its text.
  - For: the tidiest list, and the rubric was judged by whether it finds real gaps, which it did.
  - Against: nothing shows whether a good file would score well, and the one test of whether the rules are too harsh is lost.

## Why

A task line that says two things, one of them false, is worse than two lines that each say one true thing.

## Consequences

- Item 23 no longer names the three files or their gaps. Those gaps are tracked by the D2 decision (see `2026-11-21-fix-design-gaps-the-scorecards-found`, once it is recorded), so item 26 points there.
- Not built by this ADR: any change to the three design files. Item 26 stays open until a re-score shows `ready`.

## Source

Written on 2026-11-21 by Claude Code from the owner's answer on `.scratch/issue-55-follow-ups.json`, decision `D1`. The answer is the owner's, not new.
