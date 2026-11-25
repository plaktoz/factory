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
| | 4 | 4 | 3 | 4 | 3 | needs-changes |
| | 5 | 4 | 4 | 3 | 4 | needs-changes |
| `docs/design/modules/05-workflows-and-plugins.md` | 4 | 4 | 3 | 3 | 4 | needs-changes |
| `docs/design/modules/17-housekeeping.md` | 4 | 4 | 3 | 4 | 3 | needs-changes |

No design file reached `ready`. The recommendation did not change between runs for any of them, but individual scores moved by one point (module 5, Failure and Buildability, 4 to 3).

**Run 3 (re-score after the spec fixes, 2026-11-21).** Run 3 scored each file once, on the rules in this folder, after the gaps from runs 1 and 2 were edited into modules 5, 14 and 17 (commit `6a69067`, task 33). No file reached `ready`; each is held by one or two 3s. Against run 2: module 5 gained a point on Scope and on Failure; module 14 gained a point on Soundness and on Failure; module 17 did not move. Module 17's Soundness and Buildability stay at 3 on gaps that the scorer quoted from the file and I checked: L99 still calls the `apply` lock behavior "a possible bug" against the L53 rule, and L128 still says "the owner decides" which `worker.log` rule holds. One run per file is not a measure of spread (see the strong ADR runs below).

Gaps the run 3 scorers found, each checked against the file (module 17 L99, module 5 L281, module 9 L67, and no `usage_unreadable` entry in module 6):

- Module 5: L281 says a task has "both or neither of skill and cmd", but a plugin task may have only `run` (L229 to L231). `insert` does not say how `needs` is wired for the inserted stage and the stages after it. `tasks_from: languages` does not fit `expand_tasks_from(stage, artifact: Path)`. `expand_helpers` output and the plugin manifest fields are not specified.
- Module 14: it does not say which `worktree` and `branch` `start_attempt` records. The `--repo` and `[run]` choice of run folders, the printed row layout and the `--json` shape are not given. The `attempt_started` and `attempt_ended` payloads and the `schema_version` value are not given. Module 6 L243's event catalogue omits `usage_unreadable`, and module 9 L67's diagram says "tokens per model" where module 14 L20 says tokens are not split per model.
- Module 17: L99 and L53 contradict (the lock rule), L5 and L67 disagree on where deletes may happen, and the L121 criterion contradicts L103 to L104. `GcItem.dirty`, `keep_bytes`, `check_unpushed` and `ended` have no meaning or format, and the `reason` values are not listed.

Gaps the scorers found and that were checked against the file:

- Module 5, L49 says `validate_workflow` does not check skill names, but the L255 docstring says it does. The license example (L203 to L217) uses `goto: fix` for `chore`, and the chore workflow has no `fix` stage. The "Depends on" list omits 17A.
- Module 17, L10 says a worktree goes when its PR is merged or closed, but L65 says `gc` has no PR state. `GcPlan` and `GcReport` have no fields in this file or in section 18, and the timeout for `cleanup_check` is not given.

**Run 4 (task 33, 2026-11-22, one pass of fixes, then one re-score).** After the pass, each file was scored once by an independent scorer that read only `SKILL.md` and the file. I set my own scores first and had module 14 as `ready` and module 17 Buildability as 4; the scorers disagreed and I checked each finding against the file and the code. Module 14: Soundness 3 and Buildability 3. The Soundness finding is real: L49 says a task with no `usage.jsonl` gives an empty list, and L50 said it was recorded as `null` with a warning. The code (`_read`) returns an empty list and writes no warning, so L50 was corrected after the score. Its Buildability gaps are not fixed: how `start_attempt` knows a line was already reported, how an attempt number is read from a torn line, the JSON shape of `total`, how tests fix the clock, and no criterion for minutes, offset days or the invalid-exit error. Module 17: Soundness 3 and Buildability 3. Real findings: L53 against L112 (the apply-time lock, now worded as a known defect at L112 but still contradicting L53); L17 against L124 (orphans listed by `factory gc`, which the CLI does not do); how `plan` finds orphans is not stated, and `Orphan.reason` has no value list. One scorer claim was wrong: the L162 row's line numbers are not stale. Module 6's `auto_gc` line (L68) contradicts module 17 L55; module 6 is not in this task's scope. Module 5's independent scorer returned Soundness 3 and Failure 3, Buildability 4, and it is the row in the table. Its Soundness finding was right: this file said `language_tasks` takes an artifact file, which 17A's signature does not, and that sentence was corrected. Its Failure findings stand, and they are left open: the file does not say what happens when `srt` is missing for a plugin task, when `plugin-hashes.json` is unreadable, or when `requires.skills` names a skill not in `skills.lock`. Two of those need owner decisions, so they are not in the one pass. No file reached `ready`. The module 14 and 17 numbers were set by the scorers, and the module 14 file was edited once after its score (L50), so its score describes the file before that edit.

**Run 5 (task 33 module 14 follow-up, 2026-11-22, one pass of fixes, then one re-score).** The pass closed run 4's Buildability gaps: the `usage_unreadable` dedupe key (task id and line number, read from `events.jsonl`), the torn-line number rule (a regex over the raw text), the shape of `total`, and the clock in tests. It added the offset-day `--since` test (`test_an_attempt_belongs_to_the_day_in_its_own_offset_for_since`, which fails when the UTC day is used) and tightened the invalid-exit test to check nothing is written. The re-score was one independent scorer that read only `SKILL.md` and the file. It was told to skip the precheck; the precheck was run separately and passed. Result: Scope 4, Soundness 4, Failure 3, Buildability 4, `needs-changes`. The Failure blocker is real and is left open: the file does not say whether `start_attempt` runs under the run lock, what a second caller gets when two attempts number at once, or whether a failed or locked `usage_unreadable` append blocks the attempt (L45, L59). The scorer also noted an open contradiction, not fixed because the pass was spent: L21 says each `--json` group is "a map of key to the totals fields", while `total` is one `ModelTotals`. Module 14 is not `ready`. Task 33 stays open.

**Run 6 (task 45, 2026-11-22, one pass of fixes, then one re-score).** The four modules task 45 names were scored once each, by the author of the fixes (no independent scorer, so the scores are likely generous). All four are `needs-changes` and none is `rework`. Each gap the task listed was checked against the file and the code first: most were already closed (module 3 defaults, `InitReport`, `UpgradeReport`, the snapshot-copy, missing-config and `doctor` exit cases (module 3's Soundness is 4 on the file as it stands: its only open owner item, the canary gate, is a row of its Decisions table, not a gap in the contract). Its Buildability is 4, and the failed copy has its criterion (`test_a_failed_copy_leaves_the_old_kit_whole_and_no_scratch_folder`); the one behavior with no criterion is the `cleanup_check` 300-second timeout (L239), which the code implements (`housekeeping.py:153`) and no test covers; module 5 `expand_helpers` siblings and manifest fields; module 9 `TaskContext` count, credential folders and Codex note). What was fixed: module 6 step 7 (the tick runs no housekeeping; `auto_gc` is read by no code), the `tick.json` keys (`reminded`, `synced` keyed by repo path), the sync cursor wording and four `rework` functions missing from the 6B list; module 5's quorum criterion, ticked with its test.

| File | Run | Scope | Soundness | Failure | Buildability | Recommendation |
| --- | --- | --- | --- | --- | --- | --- |
| `docs/design/modules/06-engine-core.md` | 6 | 4 | 4 | 3 | 3 | needs-changes |
| `docs/design/modules/05-workflows-and-plugins.md` | 6 | 4 | 3 | 3 | 4 | needs-changes |
| `docs/design/modules/03-kit-and-configuration.md` | 6 | 4 | 4 | 4 | 4 | ready |
| `docs/design/modules/09-worker-adapters-and-governed-helpers.md` | 6 | 4 | 3 | 4 | 3 | needs-changes |

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

## Run 7: the Consequences spread after the new anchor (task 28, 2026-11-25)

Question: does the sentence PR #206 added to the Consequences anchor ("a cost listed under the chosen option counts only if Consequences repeats it or points to it") narrow the spread of 3 or 4 seen in runs 1 to 5? The strong ADR was recovered with `git show f3884af^:docs/adr/2026-11-17-wire-commands-next.md` and copied to a temp file outside the repo, with `SKILL.md` as it stands on `origin/main` (`1e1e786`). Three fresh independent agents each read only those two files, were told to treat the ADR as `proposed`, and were told to skip `precheck.py`. The ADR is `status: accepted`, so the scorers ran on the file's text, not through the precheck. None saw this brief or another score. The scores are as the scorers returned them.

| File | Run | Options | Justified | Consequences | Recommendation |
| --- | --- | --- | --- | --- | --- |
| `docs/adr/2026-11-17-wire-commands-next.md` | 7a | 4 | 3 | 2 | rework |
| | 7b | 4 | 4 | 2 | rework |
| | 7c | 4 | 3 | 2 | rework |

Consequences evidence, as each scorer gave it:

- 7a: "Missing: a Consequences section (expected after L24, before L26 Source). The costs at L23 sit under the chosen option, and nothing repeats them or points to them, so they do not count." The only commitment on later work is in Decision, "The remaining module 16 criteria come after it."
- 7b: "missing: a Consequences section (expected after L24, before Source at L26). The deferral of four module 16 items and the engine-loop full-suite requirement appear only under the chosen option (L23). Under the 2026-11-25 owner rule they do not count unless Consequences repeats them or points to them."
- 7c: "Missing: a Consequences section, which should come after Options considered (after L24). The costs sit under the chosen option (L23). The rule counts them only if Consequences repeats them or points to them, and there is no such section."

Result:

- **Spread of Consequences: one value, 2, in 3 of 3.** The check passes on the measure the task set (runs 1 to 5 gave 3 or 4).
- **The recommendation did not vary between runs, but it moved against the earlier runs.** It is `rework` on 3 of 3, where runs 1 to 5 gave `needs-changes` on 4 and `ready` on 1. The cause is the level, not the spread: the ADR has no Consequences section, so with the new sentence the costs under the chosen option no longer count. The score fell from 3 or 4 to 2, and the lowest-score rule moves the file to `rework`.
- **Justified still moves, 3 or 4.** It is 3, 4, 3 here. It did not decide the recommendation in this run, because Consequences was lower. 7a and 7c named the same gap: no opened file, test or command for the 2026-11-17 observation, and no reason why the wiring must come before the four module 16 items. 7b scored 4 on the same text, from the quote "Both were checked by running the engine." What stays ambiguous is whether a sentence that says a check was run, with no output cited, counts as evidence for a 4.
- The anchor removed the variance on Consequences for this ADR. It did not touch the variance on Justified. This is one ADR and three scorers; it does not show that the anchor is steady on an ADR that has a thin Consequences section, where 3 against 4 is a judgment about how much to repeat.
- The anchor was not changed in this run.

## What this shows

- The weak ADR scored `rework` on both runs. The recommendation is stable for it.
- The strong ADR moved from `needs-changes` to `ready` on the same text. The cause is the Consequences anchor: it does not say whether costs listed under an option count as consequences. This is the known variance. Run 2 used a tie rule and a backfill rule added after run 1, so the two runs are not a clean repeat.
- The lowest-score rule is harsh by design. A design file with one 3 cannot be `ready`. Modules 5, 14 and 17 each have real gaps, so the result is correct for them. It also means `ready` is rare. Expect most design files to return `needs-changes` until their gaps are fixed.

## Open

- Run the strong ADR at least twice more on the same rules to measure the spread. **Done 2026-11-21: runs 3 to 5 (table above). Consequences moved between 3 and 4 in five runs, Options stayed at 4, and the recommendation was `ready` in 1 run of 5. One point of noise on Consequences is confirmed; a `ready` from a single run is not evidence.**
- Module 14 and the strong ADR have no "expected" label. They are baselines, not examples of a 5.
- The gaps in modules 5, 14 and 17 are tasks for the owner. This work does not edit those files.
