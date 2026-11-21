---
scope: repo
repo: factory
topic: revise-spec-decisions-are-recorded-as-accepted-adrs
status: accepted
supersedes: []
---

# The revise-spec decisions are recorded as accepted ADRs, one per decision

## Decision

Accepted by the owner on 2026-11-21, on page `.scratch/issue-55-revise-spec.json`, decision `D5`: option `accepted-citing-session`, the recommended option. The page called it "One ADR, marked accepted, citing this page and session".

The decisions on that page are recorded as ADRs with `status: accepted`, citing the page and the session as the owner's answer. The page offered one ADR for all eight decisions. That part changed: after pull request 64 merged, the `decision-page` skill requires one ADR and one task per decision, and the owner chose "one ADR per decision, committed" on 2026-11-21 when asked. So there are eight ADRs, named in `docs/tasks.md`, and each stands without the page.

## Context

`AGENTS.md` says an architecture choice stops work until a human accepts a `proposed` ADR. Checked on 2026-11-21: all 54 ADRs that existed before this work are `accepted`, and none was waiting. The owner answered on the page, as the 2026-11-21 ADR `2026-11-20-which-engine-serves-each-repo` was answered from a page. `records.py` requires every ADR dated 2026-11-16 or later to be named in `docs/tasks.md`.

## Options considered

- **`accepted-citing-session` (chosen, recommended).** Accepted, citing the page.
  - For: it matches how the owner's earlier decisions were recorded. A later reader sees the reasons and what was turned down. `records.py` confirms each ADR is named in the task list.
  - Against: an accepted ADR cannot be edited, so a later change needs a superseding ADR. A quality-tooling choice is on the light side of "hard to reverse".
- **`proposed-first` (not chosen).** Write it as `proposed` and wait.
  - For: it leaves room for a second person to object.
  - Against: the owner already answered, so it adds a step and no information, and the task list would carry a decision that is not open.
- **`no-adr` (not chosen).** The skill and the `AGENTS.md` rule are the only record.
  - For: the least paperwork, and the skill is easy to delete.
  - Against: why the weights and the automatic check were turned down would live only in a chat.

## Why

The repo records owner choices as accepted ADRs, and these have turned-down options worth keeping.

## Consequences

- One ADR per decision means eight files instead of one, each with its own task line.
- ADRs written before calibration finished would have recorded untested numbers (see `2026-11-21-calibrate-revise-spec-before-recording-it`). These were written after.
- The skill and `AGENTS.md` rule are changed in the same commits as the ADRs they implement, as `AGENTS.md` asks.

## Source

Written on 2026-11-21 by Claude Code from the owner's answer on `.scratch/issue-55-revise-spec.json`, decision `D5`, and the owner's later choice of one ADR per decision. The answer is the owner's, not new.
