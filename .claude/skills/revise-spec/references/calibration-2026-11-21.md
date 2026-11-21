# Calibration baseline, 2026-11-21

Five files were scored by fresh sub-agents that read only `SKILL.md` and the file. Each file's first run used the rules before three changes; its second run used the rules in this folder. The three changes: design docs are no longer scored on rejected options, a tie names every tied dimension, and a backfilled ADR is scored on its own text.

These are the recorded results, not a target. Module 17 was labelled "strong" from its tick count, and the strong ADR was expected to be `ready`. Neither was. Module 5 matched its expected `needs-changes`. The scorers' findings for modules 5 and 17 were checked against the files.

## Design docs

| File | Run | Scope | Soundness | Failure | Buildability | Recommendation |
| --- | --- | --- | --- | --- | --- | --- |
| `docs/design/modules/17-housekeeping.md` | 1 | 4 | 3 | 4 | 3 | needs-changes |
| | 2 | 4 | 3 | 4 | 3 | needs-changes |
| | 3 | 4 | 3 | 4 | 3 | needs-changes |
| `docs/design/modules/05-workflows-and-plugins.md` | 1 | 3 | 3 | 4 | 4 | needs-changes |
| | 2 | 3 | 3 | 3 | 3 | needs-changes |
| | 3 | 4 | 3 | 4 | 3 | needs-changes |
| `docs/design/modules/14-token-tracking.md` | 1 | 4 | 3 | 3 | 3 | needs-changes |
| | 2 | 4 | 3 | 3 | 3 | needs-changes |
| | 3 | 4 | 4 | 4 | 3 | needs-changes |

No design file reached `ready`. The recommendation did not change between runs for any of them, but individual scores moved by one point (module 5, Failure and Buildability, 4 to 3).

**Run 3 (re-score after the spec fixes, 2026-11-21).** Run 3 scored each file once, on the rules in this folder, after the gaps from runs 1 and 2 were edited into modules 5, 14 and 17 (commit `6a69067`, task 33). No file reached `ready`; each is held by one or two 3s. Against run 2: module 5 gained a point on Scope and on Failure; module 14 gained a point on Soundness and on Failure; module 17 did not move. Module 17's Soundness and Buildability stay at 3 on gaps that the scorer quoted from the file and I checked: L99 still calls the `apply` lock behavior "a possible bug" against the L53 rule, and L128 still says "the owner decides" which `worker.log` rule holds. One run per file is not a measure of spread (see the strong ADR runs below).

Gaps the run 3 scorers found, each checked against the file (module 17 L99, module 5 L281, module 9 L67, and no `usage_unreadable` entry in module 6):

- Module 5: L281 says a task has "both or neither of skill and cmd", but a plugin task may have only `run` (L229 to L231). `insert` does not say how `needs` is wired for the inserted stage and the stages after it. `tasks_from: languages` does not fit `expand_tasks_from(stage, artifact: Path)`. `expand_helpers` output and the plugin manifest fields are not specified.
- Module 14: it does not say which `worktree` and `branch` `start_attempt` records. The `--repo` and `[run]` choice of run folders, the printed row layout and the `--json` shape are not given. The `attempt_started` and `attempt_ended` payloads and the `schema_version` value are not given. Module 6 L243's event catalogue omits `usage_unreadable`, and module 9 L67's diagram says "tokens per model" where module 14 L20 says tokens are not split per model.
- Module 17: L99 and L53 contradict (the lock rule), L5 and L67 disagree on where deletes may happen, and the L121 criterion contradicts L103 to L104. `GcItem.dirty`, `keep_bytes`, `check_unpushed` and `ended` have no meaning or format, and the `reason` values are not listed.

Gaps the scorers found and that were checked against the file:

- Module 5, L49 says `validate_workflow` does not check skill names, but the L255 docstring says it does. The license example (L203 to L217) uses `goto: fix` for `chore`, and the chore workflow has no `fix` stage. The "Depends on" list omits 17A.
- Module 17, L10 says a worktree goes when its PR is merged or closed, but L65 says `gc` has no PR state. `GcPlan` and `GcReport` have no fields in this file or in section 18, and the timeout for `cleanup_check` is not given.

## ADRs

Both files are `accepted`. They were scored as if proposed, for calibration only. `SKILL.md` does not score accepted ADRs.

| File | Run | Options | Justified | Consequences | Recommendation |
| --- | --- | --- | --- | --- | --- |
| `docs/adr/2026-11-17-wire-commands-next.md` | 1 | 4 | 4 | 3 | needs-changes |
| | 2 | 4 | 4 | 4 | ready |
| | 3 | 4 | 3 | 3 | needs-changes |
| | 4 | 4 | 3 | 3 | needs-changes |
| | 5 | 4 | 4 | 3 | needs-changes |
| `docs/adr/2026-11-14-cmd-task-non-zero-exit-is-a-check-failure.md` | 1 | 1 | 2 | 2 | rework |
| | 2 | 1 | 1 | 1 | rework |

## What this shows

- The weak ADR scored `rework` on both runs. The recommendation is stable for it.
- The strong ADR moved from `needs-changes` to `ready` on the same text. The cause is the Consequences anchor: it does not say whether costs listed under an option count as consequences. This is the known variance. Run 2 used a tie rule and a backfill rule added after run 1, so the two runs are not a clean repeat.
- The lowest-score rule is harsh by design. A design file with one 3 cannot be `ready`. Modules 5, 14 and 17 each have real gaps, so the result is correct for them. It also means `ready` is rare. Expect most design files to return `needs-changes` until their gaps are fixed.

## Open

- Run the strong ADR at least twice more on the same rules to measure the spread. **Done 2026-11-21: runs 3 to 5 (table above). Consequences moved between 3 and 4 in five runs, Options stayed at 4, and the recommendation was `ready` in 1 run of 5. One point of noise on Consequences is confirmed; a `ready` from a single run is not evidence.**
- Module 14 and the strong ADR have no "expected" label. They are baselines, not examples of a 5.
- The gaps in modules 5, 14 and 17 are tasks for the owner. This work does not edit those files.
