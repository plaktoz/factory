---
scope: repo
repo: factory
topic: reviewer-eval
status: accepted
supersedes: []
---

# The reviewer eval stays out of `bug-fix.yaml`

## Decision

The reviewer eval does not get a `review-eval` stage in `factory/workflows/bug-fix.yaml`. It runs as its own workflow, `reviewer-eval` (`factory/workflows/reviewer-eval.yaml`), which an owner or a maintainer starts by hand with `scripts/evals/reviewers/run_trial.py`. `bug-fix.yaml` is unchanged. The eval still targets the existing `review` stage, meaning the `standards` task and the `no-blocking-findings` gate.

This follows the [P2-9 finding](../research/p2-9-reviewer-eval-trial.md), which decided to build a thin runner and not a scheduled suite. [P2-9 in phase 2](../design/phase-2.md#p2-9-explore-the-use-of-evals) keeps the scheduled run open.

## Why

- **Cost on every real fix.** A pass over 12 cases at 3 runs cost about $4 to $6 in the trial, as the harness reports it, and 20 to 30 seconds per reviewer run. A stage in `bug-fix.yaml` would pay that on every bug fix, to learn nothing about that fix.
- **It tests the wrong thing.** The stage would grade fixture changes, not the change the run made. The `review` stage already reviews the real change. A second stage that reviews planted defects measures the reviewer, not the work.
- **It puts fixtures in `factory/`.** `factory/` is the kit copied into other repos. The `ledger` fixture and its twelve cases would ship to every repo that installs the kit. The cases stay in `scripts/evals/reviewers/`.
- **It is a recurring run by another name.** A stage that runs on every bug fix is a standing schedule with the bug rate as its clock. The P2-9 finding defers a scheduled suite until real reviewer misses from pilot runs ([P2-4](../design/phase-2.md#p2-4-pilot-repo-plaktoztest-adapters)) make the cases hard enough to rank reviewers. A stage would make that decision without the evidence the finding asked for.

## What the alternative is

`reviewer-eval` has one stage, `review`, with the same `standards` task and gate as `bug-fix`. A test checks that the two stay identical, so the eval cannot drift from the stage it measures.

The workflow has no trigger. The engine has no trigger field and no code lists the workflows in `factory/workflows/`. A workflow runs only when a caller names it, and the request types in triage do not map to `reviewer-eval`. Nobody starts it except the person who runs the runner. The workflow schema rejects unknown top-level keys, so a schedule cannot be added to the file without a schema change and a new ADR.

## Known limits

- One model, reached through a gateway. A drift check needs at least two models.
- Three runs per case. A rate of 18 of 18 supports "usually", not "always".
- The cases are too easy to rank reviewers.
- The kit copies `reviewer-eval.yaml` into other repos along with the other workflows. It does nothing there unless someone names it, and it needs the runner and the cases, which are not in the kit.

## Consequences

- The runner takes its skill, output name, model, timeout and gate from `reviewer-eval.yaml`. It starts the workflow's stage itself, because the engine has no driver to start a named workflow. Module 16 (`factory run`) is wave 4 and is not built. When it lands, `factory run reviewer-eval` should replace `run_trial.py` as the entry point, and the runner's extra code should go.
- The engine prompt names the stage `review`, where the trial used `review-standards`. Results from before this change are not directly comparable with new ones.
- Maintainers run the eval when they change the `review-standards` skill, the review prompt, or the model, and read the score before shipping the change.
- A scheduled or CI run, an eval stage in any shipped workflow, and cases under `factory/` each need a new ADR.
- The module 9 prompt defects, the `review-findings` fields and how a reviewer sees the diff stay open. They are listed in the finding.
