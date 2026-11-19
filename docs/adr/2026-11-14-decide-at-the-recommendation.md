---
scope: repo
repo: factory
topic: decide-at-the-recommendation
status: accepted
supersedes: []
---

# Small, reversible choices are decided at the recommendation

## Decision

A session applies the recommended option itself and logs it as "decided at recommendation, reversible". It does not ask the owner, unless the choice:

- reopens D1 to D14 or an ADR;
- changes scope or phase;
- costs a lot to reverse; or
- has no option that is clearly better.

A finding that a check can settle is fixed, with the check's output shown. A finding that needs a machine or a login the session does not have becomes a task in `docs/tasks.md`. Only what is left goes to the owner, on a decision page.

The same rule is step 1 of `.claude/skills/decision-page/SKILL.md`.

## Context

On 2026-11-14, during the design rounds, the owner wrote: "remove the need for keep asking for my decision. either frontload the decision or for small impact decision go ahead with recommendation." Over four rounds that day 27 decisions were asked. The owner took the recommended option in 26 of them; the other was marked NOT SURE.

## Source

The owner's words are quoted in `746ec67:docs/reviews/design-phase-constraint.md` (the diagnosis, fix 1, which the owner asked for). The rule is also step 1 of `.claude/skills/decision-page/SKILL.md`.
