---
scope: repo
repo: factory
topic: adversarial-check-is-a-fresh-session-by-hand
status: accepted
supersedes: []
---

# The adversarial check is a fresh session started by hand; factory runs are unchanged

## Decision

Accepted by the owner on 2026-11-21, on the page "Spec-driven workflow: three calls" (decision `D3`, "Who runs the adversarial check"), with the recommended option `manual-plus-existing`, "Fresh session by hand, factory unchanged". What now holds:

- On work a person drives, a fresh agent session checks the diff against the acceptance list before the pull request is opened.
- Factory runs keep the review they have today. `bug-fix` keeps its `review` stage (`review-standards` and `review-spec`, gate `no-blocking-findings`). `chore` keeps `implement` then `verify`, with no review stage.

This ADR records the choice. The rule telling a person to start the fresh session is not yet written into `AGENTS.md`. That wording is not final, so it waits for the owner's go-ahead (task 20 in `docs/tasks.md`).

## Context

Issue #56 step 4 asks for a fresh agent session to audit the final diff against the Given/When/Then criteria before a pull request is opened. The factory already runs a review stage on `bug-fix`. The question is whether to add the same check to `chore`, or to keep the check by hand.

Checked on 2026-11-21:

- `factory/workflows/bug-fix.yaml`: the `review` stage has two tasks, `review-standards` and `review-spec`, and the gate `no-blocking-findings` (`{check: no-blocking-findings}`).
- `factory/workflows/chore.yaml`: stages `implement` and `verify` only. No review stage.
- `factory/engine/factory_engine/delivery.py` (the `review_findings_at_or_above` branch of the never-auto rules): when a run has a stage whose id starts with `review`, that rule fails, so the run waits for a person. The rule's message still says findings "cannot be read yet (no review-findings schema)", but `factory/schemas/review-findings.schema.json` now exists, so that message is stale. The behavior is what this ADR relies on. Both are read in the code, not run. `docs/tasks.md` item 4 records that the schemas are untested against live output.
- `docs/design/modules/13-delivery.md`: a chore is the only workflow the merge policy may auto-merge in phase 1.

## Options considered

- **`manual-plus-existing`** (chosen) (recommended): a fresh session by hand; factory runs unchanged.
  - For: costs one rule and no build.
  - For: keeps chores auto-mergeable, so the phase 1a pilot path is untouched.
  - For: the same result as step 4 of the issue.
  - Against: skipped when in a hurry.
  - Against: a chore run still gets no check against its acceptance list.
- **`review-in-chore`** (not chosen): add a review stage to the `chore` workflow, so every chore run is checked by a fresh worker before the pull request goes to a person.
  - For: cannot be skipped on a factory run; catches a chore that quietly changed more than asked.
  - Against: changes a shipped workflow and its tests during the pilot.
  - Against: a review stage makes the merge policy require a person, so chores would stop merging themselves until findings can be read.
  - Against: one more worker run for each chore.

## Why

The factory already runs the check where it matters most, which is `bug-fix`. The `chore` path should stay as the pilot tested it, and adding a review stage would both change that path and stop chores from merging themselves.

## Consequences

- **Changes now:** this ADR and its task in `docs/tasks.md`. No workflow, code or test changes.
- **Not built by this ADR:** the rule in `AGENTS.md` that tells a person to start a fresh session and check the diff against the acceptance list before opening a pull request. The wording is not final, so it waits for the owner's go-ahead.
- **Still true after this decision:** a chore run gets no check against its acceptance list, and a person who skips the fresh session gets no check at all. The pilot tests whether that is acceptable.

Task: `docs/tasks.md`, item 20 (not built).

## Source

Written 2026-11-21 by the Claude Code session that applied the owner's answers (session `bee82625-ef4d-4d09-bb43-45c945a7fbab`). Page: `.scratch/sdd-workflow-proposal.json`, decision `D3`, option `manual-plus-existing`. The page is gitignored and is removed once all three decisions are recorded; this ADR is the record.
