---
scope: repo
repo: factory
topic: keep-the-nine-module-5-choices
status: accepted
supersedes: []
---

# The nine choices written into module 5 where it was silent stay

## Decision

Accepted by the owner on 2026-11-21, in the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them: keep the nine choices.

Module 5 has a section, "Choices made where this file was silent (2026-11-21, issue 55)", with nine bullets: the phase 1b `any` and `quorum:N` joins; the hook keys `add_task`, `add_gate` and `replace_skill`; when a plugin's `when` is checked; what a `changed_paths` glob matches; the 10-minute hook timeout; running hooks under `srt`; the goto check on a merged plugin workflow; the rule that a plugin's `goto` names a stage in every workflow it applies to; and the license-check example's `applies_to`, narrowed to bug-fix.

## Context

The calibration scored module 5 `needs-changes`. Its line 49 and line 255 disagreed on skill-name checks, the license example's `goto: fix` had no target in `chore`, and 17A was missing from "Depends on".

## Options considered

- **Keep the nine choices (chosen).**
  - The walkthrough's option list is not in the repo, so no alternatives are listed. This record states the answer the owner gave.

## Why

The section marks each choice as made where the file was silent, so a reader can tell it from a rule the file already had.

## Consequences

- None of the nine is built in code: plugins are phase 1b. The choices bind the later build.
- A later change to one of them needs a new ADR that supersedes this one.
- Commit `6a69067`, PR #73.

## Source

Written on 2026-11-21 by Claude Code from the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them. The answer is the owner's, not new.
