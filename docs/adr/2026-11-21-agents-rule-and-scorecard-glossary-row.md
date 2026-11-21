---
scope: repo
repo: factory
topic: agents-rule-and-scorecard-glossary-row
status: accepted
supersedes: []
---

# AGENTS.md gets a revise-spec rule, and the glossary gets a Scorecard row

## Decision

Accepted by the owner on 2026-11-21, on page `.scratch/issue-55-revise-spec.json`, decision `D8`: option `rule-and-glossary-row`, the recommended option.

Two edits, in the same change as the skill:

- `AGENTS.md`, under Working rules: "Before you mark a change to `docs/design/**` or a `proposed` ADR done, run the `revise-spec` skill. It is advice, not a gate. Make at most one pass of fixes, then report the scorecard."
- `docs/design/phase-1.md`, glossary in section 2, one row: Scorecard, "An advisory result from the `revise-spec` skill: a 1 to 5 score per dimension and a recommendation (`ready`, `needs-changes`, `rework`). Not a gate or an approval.", do not call it "review" or "approval".

## Context

Checked on 2026-11-21: the glossary defines Gate as "a deterministic check a stage must pass" and Approval as "a human stop", and lists "review" as a word not to use for approval. `AGENTS.md` had no rule about scoring a spec. A reader seeing "scorecard" or "approved" could take it for a gate.

## Options considered

- **`rule-and-glossary-row` (chosen, recommended).** Add both.
  - For: agents learn when to run it and what the word means. "Gate" and "approval" stay reserved for the engine's meaning.
  - Against: it adds a line to `AGENTS.md`, which every agent reads. The glossary row helps only people who read the glossary.
- **`rule-only` (not chosen).** The `AGENTS.md` rule alone.
  - For: the smaller change.
  - Against: "scorecard" can be read as a gate or an approval, against the glossary's one-word-per-idea rule.
- **`glossary-only` (not chosen).** The glossary row alone.
  - For: `AGENTS.md` stays as short as it is.
  - Against: agents often will not run the skill, so the consistency goal fails.

## Why

The rule makes agents use the skill, and the glossary row stops "scorecard" being mistaken for a gate.

## Consequences

- `AGENTS.md` and `docs/design/phase-1.md` change in the commit that records this decision.
- The skill's own wording says "recommendation", not "status" or "approval", to match the row.
- Not built: a check that finds a scorecard used in the docs with a different meaning.

## Source

Written on 2026-11-21 by Claude Code from the owner's answer on `.scratch/issue-55-revise-spec.json`, decision `D8`. The answer is the owner's, not new.
