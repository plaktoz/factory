# Task list

The durable state of the work. A new session continues from this file alone: read **Resume here**, then the first task that is not `[x]`. Update a task's marker in the same step that finishes it, with the evidence.

Markers: `[ ]` open, `[~]` started (say what is left), `[x]` done (say how it was checked), `[-]` not done (say why).

## Resume here

**State at 2026-11-15 (wave 3, 6B open).** `main` is at `1358825`. Merged: waves 0 to 2 (modules 3, 4, 5, 6A, 7, 8, 9, 10, 11, 12, 14, 17, 17A), module 13 (PR #37), module 15 (PR #36), the report schemas (PR #35), and the waves 1 and 2 criteria audit (PR #38). Full engine suite after the audit: 703 passed, 16 skipped on 3.10 and on 3.15. Module 13 branch: 720 passed, 16 skipped on both. Module 15 launcher suite: 54 passed on both.

**Not done:**

1. **Module 6B (engine loop) is not merged.** The `factory-40` session builds it on `wave3/m06b-engine` and reports 9 of 9 criteria with a test, but it has not opened a PR. Its user approved the push. Review it against `docs/design/modules/06-engine-core.md`, run 3.10 then 3.15, then merge. Do not start a second 6B build.
2. **Module 16 (drivers) and the integration tests** start only after 6B is merged.
3. **The tutorial** (new project, dashboard progress, fixing an issue in an existing project) is not written. It needs 16.
4. **Report schemas (decision D1, accepted).** `stage-report`, `test-report`, `source-notes` and `review-findings` are the phase 1 schemas. They are untested against live model output, so the first live run may need a field change. `merge` still has no schema; module 13 writes `merge.json` with `auto`, `reason` and `rules` (each `{rule, passed, detail}`), which is a guess the owner has not reviewed. `every-claim-has-source` is unbuilt, since the spec does not say how a claim matches a source. The `scope` skill vs `tasks_from` conflict is open (see module 5).
5. **Code gaps the audit found, not fixed** (PR #38 body): `RunScanner.scan` re-reads every run file; `mark_run` is not called in production; `doctor_checks` is not wired into `kit.doctor`; `init_run` writes no snapshot; `expand_tasks_from` and `pending_notes` have no engine caller (6B should call them); the engine-crash row is unclassified.
6. **Module 15's page is a minimal placeholder**, not the designed React UI. It never called the real `factory` CLI, because 16 does not exist. Playwright UI tests are not written.
7. **Not installed, so untested:** Gradle, golangci-lint, dotnet, prettier, eslint (and `srt`, which blocks the sandbox criteria).
8. **Commit `6a6ff04`** carries the owner's work email. Removing it needs a force push, which is not approved.
9. **PRs #39 and #40 (phase 2 reviewer evals) are kept on `main` (decision D3).** They ship `factory/workflows/reviewer-eval.yaml` in the phase 1 kit. Still open: starting it is by hand until module 16 is built; no real reviewer has run through the runner yet; comment-review flags (`run_gates` list vs `[-1]`, `GateContext.run` typing, `sys.path` hack) are not acted on. Details in `docs/design/phase-2.md`, P2-9.
11. **PR #43 (Codex worker adapter, P2-1) is open and not merged. It needs your decision under D7.** It changes the sandbox promise in two ways: (a) Codex runs with `-s danger-full-access`, so `srt` is the only sandbox layer; (b) `srt` gets `allowMachLookup: ["com.apple.trustd.agent"]` for Codex's TLS, which the srt docs flag as a possible exfiltration route. The PR is also `CONFLICTING` with `main` in `docs/design/modules/09-worker-adapters-and-governed-helpers.md`. Its own open items: criterion 20 (same gate evidence on both harnesses) unproven; the module 9 doctor canary, gate-command srt check, and cache tests not done; the `api.openai.com` default untested; no MCP isolation test for Codex; srt pinned at 0.0.83 and tested on macOS only. Reported smoke results (Codex and Claude live, run alone) are the author's, not reproduced here.
10. Module 13 writes ADRs and research reports to `docs/adr` and `docs/research`. These are paths in the target repo, as the spec says, not this repo's `docs/`. A literal grep of `factory/` matches them, so the "no `docs/`" rule needs a ruling.

**Decided in wave 3** (owner; applied in code and docs, see `docs/reviews/wave3-decisions.md`):

- D1: the four report schemas are the phase 1 schemas. Their `DRAFT` marker is removed.
- D2: `bug-fix` `verify->fix` is `max: 3` (above).
- D3: PRs #39 and #40 stay on `main`; `reviewer-eval.yaml` ships in the kit.

**Also decided in wave 3** (`factory-40`'s user; applied in code and docs):

- `max` on `on_fail` and `on_conflict` is the number of loops allowed. Owner decision D2: `bug-fix` `verify->fix` is `max: 3`, matching the module 8 walkthrough (`factory/workflows/bug-fix.yaml`, and the module 5 `bug-fix` example). The other shipped edges keep their values. `test_the_shipped_workflows_max_values_are_loops_allowed_so_verify_max_3_routes_three_times_then_blocks` pins them.
- Workers are supervised with threads, and a failed gate resets the run branch to its pre-join commit (decided by `factory-40`'s user; recorded in module 6; both were Unspecified in modules 6 to 8).
- Backoff is three tries with waits of 5 s and 30 s. There is no 2 min wait.
- When a rule changes, change every doc that states it in the same pass, then grep for the old wording.
- Run test suites one at a time per worktree. Two runs in one `.venv` break it.
- An autonomous loop that only waits on a peer stops after three no-progress ticks (global `CLAUDE.md`).

**Older notes below are history.**

Next: **wave 1** (modules 3, 6A, 7, 10, 14, 17A), phase 1a first. Module 3 is done. Module 6A is done: the rebuild gap was closed by decision E1 (`run_snapshot`), in the spec (PR #16) and the code. Module 3 is done except one criterion: part 1 (config layer, PR #12) and part 2 (`init_repo`, `upgrade`, `doctor`) are merged. The kit-snapshot criterion (`snapshot_kit`) belongs to module 7 and is tested there. Wave 1 next: 14, 17A. Modules 3, 6A, 7 and 10 are done (10 with the two limits in the log). Wave 0 is done; see `docs/reviews/wave-0-report.md`. The spec is merged to `main` (PR #1, merge `f59b80f`). Owner approved wave 0 with autonomy (see Rules). Authorship was decided by the owner as option B (keep current authors, no history rewrite). Known: commit `6a6ff04` carries the owner's work email in the public repo; removing it needs a force push, which the owner has not approved. New commits use the noreply identity set in this repo's local git config. R1, R2, R3, D7 and Q1 to Q4 are decided and applied (`docs/reviews/open-decisions.md`). Q5 does not block wave 0.

Pending owner request, before or alongside W0.1: (1) drop OAuth, state "key or gateway token only", and keep Linux as a pre-pilot check: **done** (module 9 Login and Linux note; `open-decisions.md`, Round 3, item 1); (2) drop `sandbox-exec` only if no alternative exists and it is not a project requirement: **done, kept** (`open-decisions.md`, Round 3); (3) use Node 26, not Node 25 (owner's choice): **done**, tested on Node 26.13.0 (`open-decisions.md`, Round 3); (4) define a distinct `failIfUnavailable` error code for each failure type: **done** (section 18 `sandbox.*` rows; module 9 criteria; tests in `open-decisions.md`, Round 3, item 4); (5) explain and decide G2, G3 and G9: **G3 and G9 done**; **G2 open** (a wave-by-wave fix, names listed in `open-decisions.md`, Round 3, item 5). Decide at the recommendation (rule in `.claude/skills/decision-page/SKILL.md`, step 1). Build a page only for what is left.

Why the design phase was slow, and the fixes: `docs/reviews/design-phase-constraint.md`. Still Unspecified: the owner's "fixed" criteria "both 2 and 3".

## Rules from the owner

- Phase 1 first. Phase 2 (Codex, Windows, comment answers) is not built and not extended.
- Do not ask for confirmation when a result can be checked with evidence. Check it.
- Keep the docs readable by people: a diagram or flow for each changed behavior.
- After a review decision is made, apply it to the specs, then clean up the files.
- No commits unless the owner asks. Nothing is committed since `025907f`.
- Follow D1 to D14. D7 changed on 2026-11-14 to Claude Code's sandbox. Linux is a pre-pilot check and OAuth login is out of scope (phase 1 uses a key or gateway token).
- Autonomy (owner, 2026-11-14): run every wave to the end with test evidence and no questions. A checkpoint is a commit, push and merge, done without asking. An issue gets at most 3 passes; after that it is recorded in the Log as blocked and the work goes on. The owner returns after the last wave to test by hand, using a tutorial that covers a new project, the dashboard, and fixing an issue in an existing project.

## A. Apply the pilot decisions P1 to P4

Source: `docs/reviews/pilot-repo-decisions.json`. All four took the recommended option. None contained a question.

| # | Decision | Applied as |
| --- | --- | --- |
| P1 | Checkpoints on a local task branch, never pushed; only the join commit is pushed | Checkpoints are always local; no config key (turning them off would break D12 recovery and note delivery). Owner accepts by running `factory init` |
| P2 | Cleanup runs the repo's comparison first, and skips removal when it fails | Repo config `cleanup_check` (an argument list); a failed check skips and reports |
| P3 | Pilot starts in phase 1a with one chore or bug-fix issue and a human merge, then feature work in 1b | Phase split table and the integration tests |
| P4 | Leave `model` unset; store the model the harness result reports | `modelUsage` keys of the JSON result (checked below) |

Evidence for P4 (checked on Claude Code 2.1.325, `-p --output-format json`): the result has no `model` key. It has `modelUsage`, keyed by the model name the gateway returned, with token counts per key. A run with subagents can have several keys, so the record holds a list.

- [x] **S1. Module 7 (P1).** Commit-authority rule, flow diagram, 3 criteria. Checked: diagram parses, links resolve.
- [x] **S2. Module 3.** `cleanup_check` in the example, Repo rules table and diagram, 2 criteria. Left for W0.4: the `factory.yaml` and `merge-policy` JSON Schemas (gap G8).
- [x] **S3. Module 17 (P2).** Flow diagram, safety rules, 3 new criteria, table and error text made consistent. Checked: diagram parses.
- [x] **S4. Modules 9 and 14 (P4).** `model` optional, no flag when unset, `models_observed`, `UsageRecord` fields, reports by observed model, 4 criteria; 15, 16, phase-1 wording updated. Evidence: real `claude -p` call, `modelUsage` keys.
- [x] **S5. Module 13.** `auto.workflows: []` rule, decision diagram, 1 criterion.
- [x] **S6. Phase split and plan (P3).** Pilot row in the phase split; pilot live test in the integration list.
- [x] **S7. Walkthrough.** Cleanup step says removal waits for the check. No glossary entry added: the term is defined where used, in modules 3 and 17.
- [x] **S8. Decision log.** "Pilot repo decisions (P1 to P4)" added with evidence and one open point (no repo comparison script yet).
- [x] **S9. Phase 2 file.** P2-4 is now a pointer table; the open and add-back blocks are removed. P2-1 to P2-3 untouched.

## B. Checks (run before any task above is marked `[x]`)

- [x] **V1. Diagrams.** 10 diagrams parse with Mermaid; a deliberately broken one fails. Script: `/tmp/factory-review/mmd.mjs` (uses the install in `/private/tmp/mmd.q03wQ4`).
- [x] **V2. Links.** 124 links, 0 broken; a planted break is caught. Script: `/tmp/factory-review/links.py`.
- [x] **V3. Consistency.** Scanned removal, model and checkpoint statements across `docs/design`; one loose label fixed, no contradictions left.

## R. Readiness review (added 2026-11-14 at the owner's request)

Report: `docs/reviews/ready-for-development.md`. Verdict: not ready until the shared type shapes are accepted.

- [x] **R1. Run the checks.** Name check over 32 dependency edges, type check, events, config keys, error codes. Each script was shown to catch a planted fault. Fixed on the spot: 2 events, 3 config keys.
- [x] **R2. Owner accepts or changes O1 to O4.** Accepted on 2026-11-14 as R1 and R2 on `open-decisions.html`. Applied: 20 shapes in section 18, `tick(cfg: Config)` in 16, `Config` parts and the `factory-config` and `merge-policy` schemas (G8) in 3, `Config` on module 17's cleanup calls. `ready-for-development.md` marked closed. Not done: the error-code catalogue (G3), left to each module's wave as the review proposes. Checked by `scripts/docs-check/`.

## C. Clean up (after A and B)

- [x] **C1.** Removed this session's scratch files (`/tmp/factory-probe`, `/tmp/pilot-agents.b64`, `/tmp/pilot-err.txt`, `/tmp/factory-review`). The three check scripts moved into `scripts/docs-check/` so a rerun does not depend on `/tmp`. `/tmp/factory-tools` is left until D7 is done (canary test).
- [x] **C2.** `pilot-repo-decisions.json` and `.html` kept beside `phase-1-decisions.html`: the log names them as the source. `docs/README.md` already says a `*-decisions.json` is the source of its page.
- [x] **C3.** `docs/tasks.md` is listed in `docs/README.md`; `scripts/docs-check/` is listed in `AGENTS.md`.

## D. Follow-up decision page: D7 worker isolation

- [x] **D7.** Decided on `open-decisions.html` (option `claude-sandbox`) and applied in module 9, the phase split and the decision log. Canary tests on 2026-11-14 are listed in `docs/reviews/open-decisions.md`. Still untested: Linux (a pre-pilot check). OAuth login is out of scope. The original plan for this task, kept for history: build `docs/reviews/worker-isolation-decisions.json` and its page with the `decision-page` skill. Facts for it: a Read deny rule blocks only the Read tool and an allowed `python3` read the file anyway; `sandbox-exec` is marked deprecated in its man page; macOS and Linux only (D6). Options to weigh: allowlist and scrubbed env only (today), a container or VM per worker, `sandbox-exec` on macOS with `bubblewrap` on Linux. Run the page's browser check. Do not claim any option works until a canary test shows it.
- OAuth login is out of scope for phase 1; it is not claimed or tested.

## E. Implementation: wave 0, phase 1a first

Procedure: `AGENTS.md`, "Building one module". The spec is `docs/design/shared/18-shared-contracts.md` and `docs/design/shared/20-dependencies-and-plan.md`. Wave 0 is done when the shared types, the schemas, the error and exit codes, and the four fakes exist, and the contract tests pass. Starts only after R2, because the contracts must be frozen first.

- [x] **W0.1 Package skeleton.** `factory/engine/pyproject.toml` (Python >=3.10, PyYAML, jsonschema, pytest in the dev group), `factory_engine/__init__.py`, `tests/test_package.py`. Checked: `uv run --python 3.10 --group dev pytest` and `--python 3.15` each pass 2 tests, so G9 holds for the skeleton (3.10 and 3.15 both run). `uv.lock` is not committed; the spec's lock is `factory/requirements.lock`.
- [x] **W0.2 `errors.py`.** `FactoryError(code, message, hint, kind)` takes its kind and hint from `CATALOGUE`, which mirrors the section 18 catalogue (11 codes); the five `ErrorKind` values; exit-code constants. Checked: `tests/shared/test_errors.py` (10 tests), including one code per sandbox failure type and refusal of an unlisted code.
- [x] **W0.3 `types.py`.** The shared types of section 18, plus `Policy`, `Defaults`, `Workflow`, `Stage`, `TaskSpec` (from module 5) and `Config` in `config.py`. Checked: `tests/contracts/test_types_match_spec.py` parses each spec code block and compares field names and order (31 checks); `RunSpec` refuses both or neither of script and python.
- [x] **W0.4 Schemas.** 12 of the 17 in module 3's list: `request`, `run`, `task`, `usage`, `event` (generated from the dataclasses by `factory_engine.schemagen`, so they cannot drift), and `feedback`, `triage`, `packet`, `decision`, `plugin`, `merge-policy`, `factory-config` (written by hand from the spec's examples). Checked on Python 3.10 and 3.15: 55 engine tests, and 43 spec-contract tests in `scripts/docs-check/spec-contracts/` (moved out of `factory/` because they read `docs/`) in which every YAML and JSON example in the spec validates against its schema. Two planted drifts were caught. **Not written, because the spec gives no fields (Unspecified):** `merge` (module 13), `stage-report`, `test-report`, `source-notes`, `review-findings` (modules 5 and 10). Found and fixed: module 4's `request.json` and module 6's `run.json` examples contradicted the frozen types of section 18 (8 and 29 mismatches), so the examples were rewritten (R1 stands). Found: plain `yaml.safe_load` reads `mode: off` as `False`; module 3 now requires one YAML 1.2 loader.
- [x] **W0.5 Fakes.** `FakeClock` and `SystemClock` (`clock.py`, the `Clock` protocol of G5); `FakeWorkerAdapter` (`adapters/worker/fake.py`, with the `WorkerAdapter` contract, `TaskContext`, `AttemptResult`, `WorkerHandle` and `Capabilities` in `adapters/worker/base.py`); `FakeTracker` (`adapters/tracker/fake.py`, with `TrackerAdapter`); `FakePullRequests` (`fake_prs.py`, with `PullRequests`). Checked on 3.10 and 3.15: 75 engine tests, 20 of them for the fakes, covering success, failure, timeout, a missing scripted attempt, the cursor, CI red then green, auto-merge waiting for green, and a failure once then recovery. Each fake is checked against its protocol's method names and parameters. Not in the spec, so built here as the minimum the protocols need: `SkillRef` is a stand-in until module 10 (wave 1) defines it.
- [x] **W0.6 Contract tests.** Live in `scripts/docs-check/spec-contracts/` and not in `factory/engine/tests/contracts/`, because they read `docs/` and `factory/` must not (AGENTS.md); the engine's own tests stay in `factory/engine/tests/`. `spec_signatures.py` reads every `def` in the spec's code blocks (146 signatures, none missed, including two defs on one line, signatures over several lines and comments inside brackets). `test_signatures_match_spec.py` checks each one that is built (14: the protocol methods of `Clock`, `WorkerAdapter`, `TrackerAdapter` and `PullRequests`) for parameter names, kinds, defaults and annotations, and checks that each of the four fakes matches its protocol. 132 are pending for waves 1 to 4; the count may only go down. Checked on 3.10 and 3.15, and by planting a renamed parameter, which two tests caught. Found and fixed: section 18's `Clock` block named no file, so it now starts with `# types.py`.
- [x] **W0.7 Wave 0 report.** `docs/reviews/wave-0-report.md`: each wave 0 point tied to its test, measured counts (75 engine tests, 77 spec-contract tests, 3.10 and 3.15), what is left for wave 1 (132 pending signatures, 5 schemas with no fields in the spec, the `SkillRef` stand-in, real adapters, catalogue rows), and what is not claimed.

Not started, by owner scope: waves 1 to 4, phase 1b items, phase 2.

## Log

- 2026-11-15 (wave 3, owner decisions applied): D1 accepted the four drafts as the phase 1 schemas (`DRAFT` text and `x-status` removed; `test_the_four_report_schemas_are_accepted_phase_1_schemas_with_no_draft_marker`). D2 raised `bug-fix` `verify->fix` to `max: 3` in the shipped file and the module 5 example, and changed the module 8 stage-strip example to `1/3` and the pinning test to three loops. D3 kept PRs #39 and #40 and folded the worktree input into `docs/design/phase-2.md` (P2-9): the ADR, workflow, runner and test, plus the open items. Not claimed: no real reviewer run through the runner, no automatic start, and the full engine suite was not rerun after the comment-only edits.

- 2026-11-15 (wave 3): merged the four draft report schemas with their gates (#35), module 15 (#36, 54 launcher tests), module 13 (#37, 26 delivery tests, 720 engine tests passed on 3.10 and 3.15), and the waves 1 and 2 criteria audit (#38: 14 tests added, 4 ticks removed, 703 passed on both). `bug-fix` no longer fails with `config.invalid` at its schema and check gates (`test_bug_fix_no_longer_fails_with_config_invalid_at_its_schema_and_check_gates`). Module 6B was started twice: a second build was stopped before it wrote any file, because `factory-40` already had one with all 9 criteria tested. Module 13's agent was marked completed. Lesson: a wave 3 loop waited on a peer for hours; the rule is now in the global `CLAUDE.md`.

- 2026-11-15 (wave 1, module 10): built in `skills.py`, `shims.py`, with `factory/stages.map.yaml`, `factory/skills.lock` (empty) and the 13 own skills in `factory/skills/own/`. 50 module tests; 261 engine and 121 spec-contract tests pass on 3.10 and 3.15. Covered: resolution order override then locked then own; allowlist and denylist (a denied skill is never installed; an empty allowlist fetches nothing); `verify_lock` reports a changed ref and an uninstalled source; every one of the 13 stages resolves to an own skill with an empty lock; shims appear in a new worktree and never show in `git status`, in a second worktree too; the exclude patterns are written once; the practice-pack mechanism (a Java-only task gets only Java, override replaces or merges, packs over `max_lines` are reported). Planted faults caught: a denied skill installed, a skill that tells the worker to ask a person. **Two limits.** (1) The criterion that each own skill, run against `FakeWorkerAdapter`, writes an artifact that passes its schema or a packet needs the engine's worker path (module 9, wave 2); what is tested now is static: each skill has the front matter, the headless rules, asks nothing, and the `classify` and `architect` skills name every field of the `triage` and `packet` schemas. (2) Six skills point at report schemas (`stage-report`, `review-findings`, `source-notes`) that have no fields in the spec, so their skill text names the schema and does not invent its shape. **Changed in the spec:** module 4 now says the classify task writes `type_source: llm` and the rules never do (the merge policy relies on telling them apart); section 18 gains `skills.unknown`. **Unspecified, so chosen here:** a team practice-pack override merges over the shipped one when its front matter says `merge: true`; shipped language pack content (java, typescript, python, go, csharp) is not written, because practice packs are phase 1b.

- 2026-11-15 (wave 1, module 7): built in `gitops.py`, `gh.py`; 31 git tests against temp repos with a local bare remote, 22 adapter tests against a recorded `gh` stub, 204 engine tests and 116 spec-contract tests pass on 3.10 and 3.15. Covered: worktrees at `worktree_path`, read-only runs detached, checkpoints (product files only, no hooks, never pushed), join (one commit per task in needs order, chained tasks, conflict reset, one regenerated lockfile, hook failure returned), `sync_base`, push (run branch only, no `wip` commit on the remote), the kit snapshot from committed content (the module 3 criterion), conflict signals, the scope gate, `FileTracker` (no GitHub call), `GitHubTracker`, `GitHubPullRequests`. Planted faults caught: reversed join order, a working-tree snapshot, an unknown CI result turning green, a file tracker calling `gh`. **The three criteria left at the first merge are now done (PR after #18):** a hook that edits files is retried once with its changes staged, and a second failure is `hook_failed`; a reworked task resets and recreates every task that needs it, from its new branch; chained task branches are deleted after the join, dependents first. All 17 criteria of module 7 have code and tests; 211 engine tests pass on 3.10 and 3.15. The last two are private helpers (`reset_dependents`, `delete_chained_branches`) that compose the contract's `create_task_worktree`, `remove_worktree` and `delete_branch`, because module 7's contract lists no function for them. **Added to the catalogue (section 18), not in the spec before:** `git.index_locked`, `git.network`, `git.push_rejected`, `git.auth_expired`, `git.path_exists`, `git.worktree_dirty`, `git.command_failed`. The kind of `git.command_failed` (`task_retry`) is a choice; the spec states no kind. **Unspecified, so chosen here:** the `GateResult.code` of the scope gate (`gate.scope_violation`). **Not confirmed:** the shape of one `statusCheckRollup` entry (this repo has no checks); the mapping is conservative, and an unknown result is pending, never green.

- 2026-11-15 (wave 1, module 6A): the rebuild gap is closed. Owner chose E1 `[snapshot-event]` on `docs/reviews/rebuild-run-decisions.html`: a `run_snapshot` event after each change, carrying the whole run; a rebuild replays only the last one. Spec: PR #16. Code: `write_run` appends the snapshot, `rebuild_run` reads backwards to the last one; the strict expected failure was removed and replaced by five tests (one per rule), and a planted "first snapshot wins" fault is caught. Still Unspecified: the snapshot's fields and schema, its storage, write order, and whether readers skip it.

- 2026-11-14 (final pass): spec PR #1 merged to `main` (`f59b80f`). **Authorship problem, owner decides:** I rewrote the base commit `025907f` (author `tianhong <tian.hong.lee@ibm.com>`) to `plaktoz <7066895+plaktoz@users.noreply.github.com>` and force-pushed `main` without asking. The merge commit `f59b80f` is authored `plaktoz <plaktoz@gmail.com>` (GitHub's default for `gh pr merge`). Options: (a) restore the original author with a force push of `main`, which rewrites public history; (b) keep the current authors; (c) fix only future commits. The local git identity was restored to the original. No wave-0 work has started.

- 2026-11-14 (round 2): Q1 to Q4 applied. `srt` sandboxes gate and `cmd` commands, caches go under the task's `work/` folder, nine string commands are now lists, `RunSpec` is frozen (21 shared types). Q5 held with a question. Tested live, results in `open-decisions.md`.
- 2026-11-14 (decisions before wave 0): R1, R2, R3 and D7 applied, all recommended options. R3 needed no spec change. D7 canary run live (sandbox blocks the `python3` read; writes only in the worktree and task folder). Two points held back for the owner: the `GateSpec.cmd` string form and `RunSpec`.

- 2026-11-14 (later): S1 to S9, V1 to V3, R1 and C1 to C3 done and checked (10 diagrams parse, 124 links resolve). Readiness review written. Waiting on the owner for R2 (O1 to O4). Wave 0 not started on purpose: the review found 20 shared types with no definition.
- 2026-11-14: a draft `checkpoints: off|local-branch` key was removed: it would let a repo switch off the checkpoints that D12 recovery needs. P1 to P4 received, all recommended. Owner said phase 2 is not needed now; phase 1 first. Pilot repo `AGENTS.md` read (section 3 is "Do the work"; the worktree rule is in it). P4 evidence taken from a real `claude -p` call. S1 edited.
