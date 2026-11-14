# Task list

The durable state of the work. A new session continues from this file alone: read **Resume here**, then the first task that is not `[x]`. Update a task's marker in the same step that finishes it, with the evidence.

Markers: `[ ]` open, `[~]` started (say what is left), `[x]` done (say how it was checked), `[-]` not done (say why).

## Resume here

Next: **wave 1** (modules 3, 6A, 7, 10, 14, 17A), phase 1a first. Module 3 is split: part 1 (config, interpolation, precedence, YAML, schemas, `cleanup_check`, paths, masking, `resolve_harness`) is done; part 2 (`init_repo`, `upgrade`, kit snapshot, `doctor`) is next. Wave 0 is done; see `docs/reviews/wave-0-report.md`. The spec is merged to `main` (PR #1, merge `f59b80f`). Owner approved wave 0 with autonomy (see Rules). Authorship was decided by the owner as option B (keep current authors, no history rewrite). Known: commit `6a6ff04` carries the owner's work email in the public repo; removing it needs a force push, which the owner has not approved. New commits use the noreply identity set in this repo's local git config. R1, R2, R3, D7 and Q1 to Q4 are decided and applied (`docs/reviews/open-decisions.md`). Q5 does not block wave 0.

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

- 2026-11-14 (final pass): spec PR #1 merged to `main` (`f59b80f`). **Authorship problem, owner decides:** I rewrote the base commit `025907f` (author `tianhong <tian.hong.lee@ibm.com>`) to `plaktoz <7066895+plaktoz@users.noreply.github.com>` and force-pushed `main` without asking. The merge commit `f59b80f` is authored `plaktoz <plaktoz@gmail.com>` (GitHub's default for `gh pr merge`). Options: (a) restore the original author with a force push of `main`, which rewrites public history; (b) keep the current authors; (c) fix only future commits. The local git identity was restored to the original. No wave-0 work has started.

- 2026-11-14 (round 2): Q1 to Q4 applied. `srt` sandboxes gate and `cmd` commands, caches go under the task's `work/` folder, nine string commands are now lists, `RunSpec` is frozen (21 shared types). Q5 held with a question. Tested live, results in `open-decisions.md`.
- 2026-11-14 (decisions before wave 0): R1, R2, R3 and D7 applied, all recommended options. R3 needed no spec change. D7 canary run live (sandbox blocks the `python3` read; writes only in the worktree and task folder). Two points held back for the owner: the `GateSpec.cmd` string form and `RunSpec`.

- 2026-11-14 (later): S1 to S9, V1 to V3, R1 and C1 to C3 done and checked (10 diagrams parse, 124 links resolve). Readiness review written. Waiting on the owner for R2 (O1 to O4). Wave 0 not started on purpose: the review found 20 shared types with no definition.
- 2026-11-14: a draft `checkpoints: off|local-branch` key was removed: it would let a repo switch off the checkpoints that D12 recovery needs. P1 to P4 received, all recommended. Owner said phase 2 is not needed now; phase 1 first. Pilot repo `AGENTS.md` read (section 3 is "Do the work"; the worktree rule is in it). P4 evidence taken from a real `claude -p` call. S1 edited.
