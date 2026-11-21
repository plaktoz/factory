---
scope: repo
repo: factory
topic: spec-rules-live-in-agents-md-and-issue-form
status: accepted
supersedes: []
---

# Spec rules live in AGENTS.md, and each ticket's spec is its GitHub issue

## Decision

Accepted by the owner on 2026-11-21, on the page "Spec-driven workflow: three calls" (decision `D2`, "Where the rules and specs live"), with the recommended option `extend-existing`, "Use AGENTS.md and the issue form". What now holds:

- The rules stay in `AGENTS.md`, as an Always / Ask first / Never table.
- Each ticket's spec is the GitHub issue itself, filled in from an issue form. The form asks for Goal, Not included, Contracts, and Acceptance (Given/When/Then, with an edge case).
- There is no `specs/` folder, no second rules file and no per-ticket `tasks.md`.

This ADR records the choice. The `AGENTS.md` table and the issue form are not written by it. Their wording was drafted on the decision page and is not final, so they wait for the owner's go-ahead (task 19 in `docs/tasks.md`).

## Context

Issue #56 proposes a repo-wide rules file and a per-ticket spec folder (`specs/constitution.md` and `specs/features/<issue>-<slug>/`). This repo already has a rules file and a record of decisions, so the question is where the new rules and specs should go.

Checked on 2026-11-21:

- `AGENTS.md` is 55 lines. It holds the shared rules, which every harness reads (`docs/design/modules/03-kit-and-configuration.md`).
- `docs/tasks.md` is the project's task list, and `docs/adr/` holds the decisions. Both are in use.
- The factory kit in `factory/` is copied into other repos and may not reference this repo's `docs/` (`AGENTS.md`, Layout). A `specs/` folder in this repo would not travel with the kit.
- A GitHub issue's body reaches a factory worker, because `factory/engine/factory_engine/prompt.py` puts it under "Body:". Its `acceptance` list stays empty, because only markdown front matter fills it (probe, run on 2026-11-21, `normalize` in `intake.py`). This ADR does not change that.
- `.github/` is in the `deny_paths` of both shipped workflows (`factory/workflows/bug-fix.yaml`, `chore.yaml`). A factory worker cannot write an issue form there, so a person adds it.

The three frameworks' templates were read on GitHub, not run.

## Options considered

- **`extend-existing`** (chosen) (recommended): rules in `AGENTS.md`, spec in the issue form.
  - For: one place for rules, so they cannot drift apart.
  - For: the spec sits where the request already is, so a factory worker can read it from the issue body.
  - For: no folder of per-ticket files to keep in step with the code.
  - Against: the spec lives outside git history, so an edited issue is harder to review than a changed file.
  - Against: relies on the issue body staying put. The factory flags a body change (`request_changed`), but does not stop the run.
- **`specs-folder`** (not chosen): the issue's own layout, `specs/constitution.md` and `specs/features/<issue>-<slug>/`.
  - For: specs are reviewed in the pull request like code; agents read them from the working copy with no GitHub call.
  - Against: a second rules file beside `AGENTS.md`, so two places to keep true.
  - Against: a tasks file beside `docs/tasks.md`, which invites confusion.
  - Against: a folder that grows with every ticket, and each spec can go stale, which is the drift the issue names.

## Why

The repo already has one rules file and one decision folder. A second rules file would drift from the first, and a per-ticket folder would need upkeep.

## Consequences

- **Changes now:** this ADR and its task in `docs/tasks.md`. Nothing else is edited.
- **Not built by this ADR:**
  - The `AGENTS.md` table (Always / Ask first / Never), the rule to write the spec in the issue before building anything larger than a chore, and the rule to start a fresh session for the check. The check rule is `2026-11-21-adversarial-check-is-a-fresh-session-by-hand`. Wording is not final, so it waits for the owner's go-ahead.
  - The issue form under `.github/`. A person adds it.
- **Factory code, workflows and schemas:** no change. Making a GitHub issue fill the `acceptance` list is a separate build task and is not part of this decision.

Task: `docs/tasks.md`, item 19 (not built).

## Source

Written 2026-11-21 by the Claude Code session that applied the owner's answers (session `bee82625-ef4d-4d09-bb43-45c945a7fbab`). Page: `.scratch/sdd-workflow-proposal.json`, decision `D2`, option `extend-existing`. The page is gitignored and is removed once all three decisions are recorded; this ADR is the record.
