---
scope: repo
repo: factory
topic: spec-workflow-applies-by-hand-first
status: accepted
supersedes: []
---

# The spec workflow is a by-hand pilot on two tickets before any factory change

## Decision

Accepted by the owner on 2026-11-21, on the page "Spec-driven workflow: three calls" (decision `D1`, "Where the workflow applies"), with the recommended option `house-rule-first`, "House rule first, factory later". What now holds: you and your agents follow the spec steps by hand on two medium tickets for two weeks. The factory does nothing new. Whether to build the steps into a factory workflow is a later decision, taken after the pilot, in its own ADR.

The other two calls on the same page are recorded in their own ADRs: `2026-11-21-spec-rules-live-in-agents-md-and-issue-form` (`D2`) and `2026-11-21-adversarial-check-is-a-fresh-session-by-hand` (`D3`).

## Context

Issue #56 (https://github.com/plaktoz/factory/issues/56) proposes a spec-driven workflow for agentic coding, a hybrid of three frameworks: a rules file with Always / Ask First / Never tiers (GitHub Spec Kit), a short per-ticket spec with an "Explicitly NOT Included" section (OpenSpec), and an adversarial check by a fresh agent against Given/When/Then criteria (BMAD-METHOD). The issue asks for a two-week pilot on two medium tickets before any tooling is built.

Checked on 2026-11-21:

- The shipped workflows are `bug-fix` and `chore` (`factory/workflows/`). The feature workflow is phase 1b (`docs/design/phase-1.md`, the workflow row of the phase table).
- A GitHub issue body with a Given/When/Then checklist gives an empty `acceptance` list. Probe: `normalize` in `factory/engine/factory_engine/intake.py`, run on a GitHub-sourced request. Only a markdown request with front matter fills that list. The issue body itself does reach a worker: `prompt.py` puts it under "Body:" (read in the code, not run).
- Phase 1a is not finished: two-kit dispatch and a live Claude worker run are open in `docs/tasks.md`.

The three frameworks' READMEs and templates were read on GitHub, not run.

## Options considered

- **`house-rule-first`** (chosen) (recommended): follow the spec steps by hand on two tickets for two weeks, then decide whether the factory should do it.
  - For: matches the issue's own plan, a pilot before any tooling.
  - For: no change to the open phase 1a build.
  - For: if the steps do not pay off, nothing is undone.
  - Against: enforced by habit, so a hurried ticket can skip it.
  - Against: a GitHub issue still gives the factory an empty `acceptance` list until that is fixed as a separate task.
- **`build-into-factory`** (not chosen): a feature run writes the short spec first and waits for approval before any code.
  - For: the step cannot be skipped on a factory run; the final review reads the criteria that were approved.
  - Against: reopens the phase 1 scope, since the feature workflow is not built; builds on an idea not yet tried on this repo; needs its own ADR and a change to the shared request type.
- **`keep-as-is`** (not chosen): adopt nothing.
  - For: zero cost; the repo already has per-module acceptance criteria, ADRs and a review stage.
  - Against: tickets stay free-form, which is the drift the issue describes; nothing records what a ticket must not touch beyond file paths.

## Why

The issue asks for a pilot first. A by-hand pilot costs a few lines in one file, while the factory build is unfinished and the feature workflow is not yet built.

## Consequences

- **Changes now:** this ADR and its task in `docs/tasks.md`. No code, workflow, schema or spec module changes.
- **Not built by this ADR:** the pilot itself. The two tickets, the person who drafts the first version of the rules, and the measures (PR review time and defect rate) are not named yet, so they are Unspecified.
- **Rule text:** the by-hand steps need wording in `AGENTS.md`. That wording is part of `2026-11-21-spec-rules-live-in-agents-md-and-issue-form`, and the task for it is in `docs/tasks.md`.
- **Revisit:** if the pilot shows the steps pay off, a later ADR decides whether to build them into a factory workflow. That ADR would supersede the by-hand parts of this one by id.

Task: `docs/tasks.md`, item 18.

## Source

Written 2026-11-21 by the Claude Code session that applied the owner's answers (session `bee82625-ef4d-4d09-bb43-45c945a7fbab`). Page: `.scratch/sdd-workflow-proposal.json`, decision `D1`, option `house-rule-first`. The page is gitignored and is removed once all three decisions are recorded; this ADR is the record.
