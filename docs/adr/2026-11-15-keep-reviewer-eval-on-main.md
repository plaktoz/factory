---
scope: repo
repo: factory
topic: keep-reviewer-eval-on-main
status: accepted
supersedes: []
---

# Phase 2 evals on main (PRs #39 and #40)

## Decision

Keep both as merged: PRs #39 and #40 stay on `main`, and `factory/workflows/reviewer-eval.yaml` ships in the phase 1 kit. The owner accepted the cost that `factory init` copies that workflow into every repo. How the eval runs is a separate decision: [the reviewer eval stays out of `bug-fix.yaml`](2026-11-15-reviewer-eval-outside-bug-fix.md).

Chosen option: `keep-both`.

## Context

Another session merged two phase 2 PRs to main: #39 (docs/research/p2-9 trial, scripts/evals/reviewers) and #40 (factory/workflows/reviewer-eval.yaml, a test, an ADR). AGENTS.md says do not build phase 2 in phase 1. #40 puts reviewer-eval into the kit that gets copied to other repos, and adds a test to the engine suite.

## Options considered

- **`keep-move-out-of-kit`** (recommended): Keep #39, and move reviewer-eval.yaml out of the shipped kit
  - For: Keeps the eval research and scripts
  - For: The kit stays phase 1 only
  - For: The kit copied into other repos has no eval workflow
  - Against: A follow-up PR is needed, including the test
  - Against: The other session's tests may expect the workflow in factory/workflows
- **`keep-both`** (chosen): Keep both as merged
  - For: No work
  - For: The eval workflow is already tested
  - Against: Breaks the phase 1 rule in AGENTS.md
  - Against: The eval workflow ships to every repo that runs factory init
- **`revert-both`**: Revert #39 and #40
  - For: main is phase 1 only again
  - For: Matches AGENTS.md exactly
  - Against: Loses research someone did on purpose
  - Against: Reverting a merged PR from another session needs that session's owner to agree

## Why

The page's reason is for the recommended option, which the owner did not choose. The owner's own reason is not recorded.

The research and scripts are outside the kit and harmless, while a workflow in the kit reaches other repos.

## Source

Backfilled on 2026-11-16 from `docs/reviews/wave3-decisions.md`, decision `D3`, page `docs/reviews/wave3-decisions.json`. The owner chose this on 2026-11-15; the answer is the record's, not new.
