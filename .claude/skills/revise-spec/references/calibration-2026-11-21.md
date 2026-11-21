# Calibration baseline, 2026-11-21

Five files were scored by fresh sub-agents that read only `SKILL.md` and the file. Each file's first run used the rules before three changes; its second run used the rules in this folder. The three changes: design docs are no longer scored on rejected options, a tie names every tied dimension, and a backfilled ADR is scored on its own text.

These are the recorded results, not a target. Module 17 was labelled "strong" from its tick count, and the strong ADR was expected to be `ready`. Neither was. Module 5 matched its expected `needs-changes`. The scorers' findings for modules 5 and 17 were checked against the files.

## Design docs

| File | Run | Scope | Soundness | Failure | Buildability | Recommendation |
| --- | --- | --- | --- | --- | --- | --- |
| `docs/design/modules/17-housekeeping.md` | 1 | 4 | 3 | 4 | 3 | needs-changes |
| | 2 | 4 | 3 | 4 | 3 | needs-changes |
| `docs/design/modules/05-workflows-and-plugins.md` | 1 | 3 | 3 | 4 | 4 | needs-changes |
| | 2 | 3 | 3 | 3 | 3 | needs-changes |
| `docs/design/modules/14-token-tracking.md` | 1 | 4 | 3 | 3 | 3 | needs-changes |
| | 2 | 4 | 3 | 3 | 3 | needs-changes |

No design file reached `ready`. The recommendation did not change between runs for any of them, but individual scores moved by one point (module 5, Failure and Buildability, 4 to 3).

Gaps the scorers found and that were checked against the file:

- Module 5, L49 says `validate_workflow` does not check skill names, but the L255 docstring says it does. The license example (L203 to L217) uses `goto: fix` for `chore`, and the chore workflow has no `fix` stage. The "Depends on" list omits 17A.
- Module 17, L10 says a worktree goes when its PR is merged or closed, but L65 says `gc` has no PR state. `GcPlan` and `GcReport` have no fields in this file or in section 18, and the timeout for `cleanup_check` is not given.

## ADRs

Both files are `accepted`. They were scored as if proposed, for calibration only. `SKILL.md` does not score accepted ADRs.

| File | Run | Options | Justified | Consequences | Recommendation |
| --- | --- | --- | --- | --- | --- |
| `docs/adr/2026-11-17-wire-commands-next.md` | 1 | 4 | 4 | 3 | needs-changes |
| | 2 | 4 | 4 | 4 | ready |
| `docs/adr/2026-11-14-cmd-task-non-zero-exit-is-a-check-failure.md` | 1 | 1 | 2 | 2 | rework |
| | 2 | 1 | 1 | 1 | rework |

## What this shows

- The weak ADR scored `rework` on both runs. The recommendation is stable for it.
- The strong ADR moved from `needs-changes` to `ready` on the same text. The cause is the Consequences anchor: it does not say whether costs listed under an option count as consequences. This is the known variance. Run 2 used a tie rule and a backfill rule added after run 1, so the two runs are not a clean repeat.
- The lowest-score rule is harsh by design. A design file with one 3 cannot be `ready`. Modules 5, 14 and 17 each have real gaps, so the result is correct for them. It also means `ready` is rare. Expect most design files to return `needs-changes` until their gaps are fixed.

## Open

- Run the strong ADR at least twice more on the same rules to measure the spread. Until then, treat a Consequences score of 3 or 4 on an ADR as one point of noise.
- Module 14 and the strong ADR have no "expected" label. They are baselines, not examples of a 5.
- The gaps in modules 5, 14 and 17 are tasks for the owner. This work does not edit those files.
