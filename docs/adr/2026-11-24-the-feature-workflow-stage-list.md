---
scope: repo
repo: factory
topic: the-feature-workflow-stage-list
status: proposed
supersedes: []
---

# What stages should the feature workflow have, and should the architecture stage be in it now?

## Decision

Question for the owner: approve the stage list for `feature` below, so it can ship as `factory/workflows/feature.yaml` and triage can pick it. It has four stages: a human approves the plan (`propose`), one worker implements it (`implement`), the repo's own check runs with a JUnit report (`verify`), and two review skills check the result (`review`).

Recommended option: **option 1, the four-stage list with no architecture stage.** Ship it first. The architecture stage waits for a separate decision on how its trigger rule and its skill packet are built, because neither exists in the engine today.

## Context

Checked on 2026-11-24 on branch `plaktoz/feature-workflow-draft` of `main` at `f1b6429`.

- **The feature workflow has no file.** `factory/workflows/` holds `_triage.yaml`, `bug-fix.yaml`, `chore.yaml` and `reviewer-eval.yaml`. `load_workflow` on the shipped kit fails: `config.invalid: no workflow named 'feature'`.
- **Triage picks `feature` anyway.** `factory/engine/factory_engine/triage.py` maps the word "add" to `feature` (`KEYWORDS`). The pilot repo's issue #38 (`plaktoz/test-adapters`) contains "add", so the rules return `feature` at confidence 0.9. `_create_run_worktree` then loads `feature` and the run cannot start. Run by `triage_rules` on the pilot issues, read-only, 2026-11-24: #32 `bug-fix` (matched "failing"), #34 `bug-fix` ("exception"), #35 `bug-fix` ("fix"), #38 `feature` ("add"), and #33, #36 and #37 match nothing, so they go to the LLM classify step.
- **The draft loads.** The four-stage list below was written to a temp folder outside the repo and loaded with `load_workflow` from the engine venv, with `PYTHONPATH` set to this branch's engine. It loads with no problems. The option 2 variant (an `architecture` stage with `skill: architect` and `approval: human` in front of `propose`) also loads, so the load check does not tell the two shapes apart; the difference is what the stop shows. Each skill it names is in `factory/skills/own/` (`propose`, `implement`, `review-standards`, `review-spec`), and each check it names (`scope-diff`, `lint-clean`, `no-blocking-findings`) is in `KNOWN_CHECKS`.
- **A gate on an approval stage never runs.** `factory/engine/factory_engine/engine.py` `_run_stage` sends a stage with `approval: human` to `_human_stop` and returns before `_join_and_gate`, which is where gates run. So a stage-report gate on `propose` would be dead. The approval is the check there.
- **The test-report gate blocks an empty verify.** `engine.py` (`_no_test_results`) blocks the run with `gate.no_test_results` when a stage's JUnit files hold zero test cases. A `cmd` task is done only when it writes its `out` file (`adapters/worker/command.py`, around line 148). The pilot repo's `scripts/check` runs `uvx --with pytest pytest -q` and writes no JUnit file, so the verify stage would block there unless `scripts/check` writes one.
- **The architecture stage has no trigger.** Module 11 (`docs/design/modules/11-human-stops.md`, line 17) says the architecture stage runs in feature "only when a rule fires", and names the rule's inputs: an architecture label, a new language, framework, datastore or service, or more than a set number of modules touched. No code reads any of those inputs. `grep` for `architecture` in `factory/engine/factory_engine/` finds only the merge rule `never_auto_if.architecture_decision` (`kit.py`, `delivery.py`), the ADR writer in `delivery.py`, and an error hint in `errors.py`. None of them decides whether a run needs the stage.
- **A skill's architect packet has no path to a stop.** `factory/skills/own/architect/SKILL.md` says to write a decision packet. `decisions.request` is called from two places only: triage (`engine.py` line 459) and the approval template (`engine.py` line 967). `decisions._template` raises `decision.no_packet` for any other stop kind. So an architect task would finish, and the engine would show a person the generic approval packet, not the architect's options. `decisions.request` does accept a skill's packet (the `packet=` argument), and `test_architecture_stop_writes_the_skills_packet` passes it a packet the test builds (`tests/decisions/test_decisions.py`, `stop()`). What is missing is the engine code that reads an architect task's artifact and makes that call.
- **Feature does not auto-merge.** `factory/engine/factory_engine/kit.py` ships `auto.workflows: []`, and module 13 says a repo that approves every task keeps it empty. Feature is not in the list, so every feature pull request waits for a person.
- **Available skills.** `factory/skills/own/` holds architect, classify, critique, fix, gather, implement, propose, reproduce, review-spec, review-standards, root-cause, scope and synthesize. The stage-to-skill map is `factory/stages.map.yaml`. No skill is missing for the four stages. The only skill needed for the architecture stage is `architect`, and it exists.
- **No practice pack is used.** `factory/skills/own/practices/` holds only `.gitkeep`, and the engine passes `practices=[]`, so no stage needs one.

## Options considered

1. **Four stages, no architecture stage (recommended).** `propose` (human approval), `implement`, `verify` (`scripts/check` with JUnit, `test-report` gate), `review` (`review-standards` and `review-spec`, `no-blocking-findings`). For: every stage uses a skill or check that works today; the approval and the review cover what the owner needs before merge; once the pilot's `scripts/check` writes JUnit, it lets the pilot's jest issues run. Against: a feature that needs an architecture choice gets no architecture stop from this workflow, so the owner must decide those by hand until option 3 is built. It also needs the pilot's `scripts/check` to write JUnit, or the verify stage blocks there.
2. **Add an architecture stage now, before `propose`, with `approval: human`.** `architecture` runs the `architect` skill and then waits for approval. For: it matches the module 11 picture, so the owner sees the architecture step in the workflow. Against: the approval stop shows the generic approve, rework, reject packet from `_approval_packet`, not the architect's options. The architect skill's packet never reaches a person, because no engine code writes it to a decision file. A feature would pause at that generic stop, and the person could approve it without seeing any architecture choice. It also runs the architect on every feature, although module 11 says only when a rule fires, and there is no rule to evaluate. The run can finish, but the stage does not do what module 11 says it does. That follows from the code I read, not from a run of the stage.
3. **Two-workflow route: `feature` stays four stages, and an `architecture-feature` workflow (or an `on_*` route) takes features that trip the rule.** For: the rule stays out of the stage list until the rule is built, and the common path is unchanged. Against: a second workflow file and a router that does not exist yet; the trigger inputs still need an evaluator. This option is not built or tested and is listed to show the shape the rule needs, not as a near-term choice.

## Why

Option 1 is the only shape in which every stage does what its name says with what exists today (option 2 loads and can finish, but its architecture stop cannot show a person the options). It runs every stage through a skill or check that exists, and does what the owner needs first: a person approves the plan, the change is verified and reviewed, and nothing merges unreviewed. Option 2 looks closer to module 11, but the architect's packet has no route to a person, so the stage would pause with a generic approval and the architecture choice would never be made. Option 3 needs a rule evaluator and a second workflow, which is more than this step should decide. Shipping option 1 first lets the pilot's jest issues run once its check writes JUnit, and the architecture stage can be decided once the rule and the packet route are designed.

## Consequences

- If option 1 is approved, the next step (not in this change) is to add `factory/workflows/feature.yaml` with the list below, with a test that it loads. `triage_candidates` already offers `feature` once it loads (checked 2026-11-24 by passing a load check that accepts it: the pilot issues then list `bug-fix`, `chore` and `feature`), so no triage code changes. Triage's keyword route to `feature` then loads. Module 5's feature row changes from "none" to the shipped file, and the proposal section is replaced by the file's text.
- The pilot repo's `scripts/check` must write a JUnit file before feature runs there (`pytest --junitxml=...`). That is a change to `plaktoz/test-adapters`, not to this repo.
- The approval packet does not show the plan. `propose` writes `plan.json`, but the person sees the generic packet. This gap also exists in bug-fix. Fixing it is a separate decision.
- Architecture is not in the workflow. Any feature that needs an architecture choice must be run by hand until option 3, or a rule evaluator plus a packet route, is decided.
- Feature stays out of `auto.workflows`, so every feature pull request waits for a person. This matches module 13.
- The draft is the four-stage list below. A later change to any stage is a change to module 5's proposal section and, once the owner accepts, to the file.
- Supersedes: none.

**The stage list (proposal)**

```yaml
name: feature
type: feature
sink: pull_request
policy: {write: true, deny_paths: [".github/**"]}
defaults: {retries: 2, timeout_minutes: 30, checkpoint_every_minutes: 10, max_restarts: 3}
stages:
  - id: propose
    tasks: [{id: plan, skill: propose, out: plan.json}]
    approval: human
    on_reject: {goto: propose}
  - id: implement
    needs: [propose]
    tasks: [{id: change, skill: implement, scope: ["**"], helpers: {mode: off}, out: change.json}]
    gate: [{schema: stage-report}, {check: scope-diff}, {check: lint-clean}]
    on_fail: {goto: implement, max: 2}
    on_conflict: {goto: implement, max: 1}
  - id: verify
    needs: [implement]
    tasks: [{id: check, cmd: [scripts/check], out: check.junit.xml}]
    gate: [{schema: test-report}]
    on_fail: {goto: implement, max: 2}
  - id: review
    needs: [verify]
    tasks:
      - {id: standards, skill: review-standards, out: standards.json}
      - {id: spec, skill: review-spec, out: spec.json}
    join: all
    gate: [{check: no-blocking-findings}]
    on_fail: {goto: implement, max: 1}
```

## Source

Facts checked by running or reading the code on 2026-11-24, on this branch: `factory/engine/factory_engine/workflow.py` (`load_workflow`, `KNOWN_CHECKS`); `factory/engine/factory_engine/triage.py` (`TYPE_WORKFLOW`, `KEYWORDS`, `triage_rules`, `triage_candidates`); `factory/engine/factory_engine/engine.py` (`_run_stage`, `_human_stop`, `_join_and_gate`, `_no_test_results`, `_create_run_worktree`, lines 459 and 967); `factory/engine/factory_engine/decisions.py` (`_approval_packet`, `_template`, `request`); `factory/engine/factory_engine/kit.py` (`auto.workflows: []`); `factory/engine/factory_engine/adapters/worker/command.py` (a command task's `out` file); `factory/stages.map.yaml`; `factory/skills/own/*/SKILL.md`; `docs/design/modules/05-workflows-and-plugins.md` (feature row and proposal); `docs/design/modules/11-human-stops.md` (architecture stage, line 17); `docs/design/modules/13-delivery.md` (auto workflows); `plaktoz/test-adapters` issues #32 to #38 and `scripts/check`, read only with `gh`. The draft was loaded from a temp folder outside the repo, not committed.
