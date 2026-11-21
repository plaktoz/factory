---
scope: repo
repo: factory
topic: revise-spec-runs-on-request
status: accepted
supersedes: []
---

# revise-spec runs on request, with a rule in AGENTS.md and one fix pass

## Decision

Accepted by the owner on 2026-11-21, on page `.scratch/issue-55-revise-spec.json`, decision `D3`: option `on-request-with-pointer`, the recommended option.

Nothing runs the skill automatically. A person can run it at any time. `AGENTS.md` tells an agent to run it before it marks a change to `docs/design/**` or a `proposed` ADR done. If the result is `needs-changes` or `rework`, the agent fixes the blocking items and runs once more. If the second result is not `ready`, the agent reports the scorecard to the person and stops. The skill is advice. It is not a gate, a hook or a workflow stage, and it blocks no merge.

## Context

Checked on 2026-11-21: the repo has no `.github/` folder, so there is no pull request template and no continuous integration. The `bug-fix` workflow denies workers edits to `.github/**` (`factory/workflows/bug-fix.yaml`), so an automated check would be added by hand. The spec checks in `scripts/docs-check/` are run by hand. Design changes are often made by agents alone in a worktree. LLM scores vary between runs (see the calibration record).

## Options considered

- **`on-request-with-pointer` (chosen, recommended).** On request, plus an `AGENTS.md` rule, one fix-and-rerun pass.
  - For: no new automation to maintain. The single pass stops an agent looping on its own score. The person sees the scorecard whenever the result is not `ready`.
  - Against: it depends on agents following the rule, and nothing catches a skipped run. An agent scoring its own work can be generous.
- **`on-request-only` (not chosen).** No rule in `AGENTS.md`.
  - For: the smallest change.
  - Against: most design changes would never be scored, so the issue's consistency goal is not met.
- **`automatic-on-pull-request` (not chosen).** Run on every pull request that touches design files.
  - For: nothing can be skipped, and everyone sees the same scorecard.
  - Against: the repo has no automation today. Scores vary, so a posted number may look more certain than it is. It runs a model on every pull request, at a cost.

## Why

An advisory rule puts scorecards into agent work without adding automation this repo does not have.

## Consequences

- The `AGENTS.md` rule is written by the decision recorded in `2026-11-21-agents-rule-and-scorecard-glossary-row`.
- Revisit enforcement after several scorecards exist. The calibration record says the spread on an ADR is not yet measured.
- Not built: any continuous integration job or pull request template.

## Source

Written on 2026-11-21 by Claude Code from the owner's answer on `.scratch/issue-55-revise-spec.json`, decision `D3`. The answer is the owner's, not new.
