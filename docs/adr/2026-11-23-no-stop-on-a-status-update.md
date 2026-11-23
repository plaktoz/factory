---
scope: repo
repo: factory
topic: no-stop-on-a-status-update
status: proposed
supersedes: []
---

# A session does not end its turn on a status update

## Decision

Question for the owner: should a working rule in `AGENTS.md` say that a session ends its turn only when it asks a question, lists what waits on the owner, or delivers a pull request, and not on a progress update?

Recommended option: **add one line to Working rules**, so a session reports progress in its next message and keeps working. You chose this option on the retro page (finding F1, 2026-11-23). It changes a rule the owner set, so it waits here until you accept it.

## Context

- The retro over 66 sessions (2026-11-14 to 2026-11-22) counted 283 replies under 30 minutes. 129 of them (about 10 hours of gaps) came after a message that ended on a status update and asked nothing. The kind was read from each last message by keyword, so the split is an estimate. Checked by hand on six samples: four were mis-filed as status until a "blocked" kind was added, which moved 20 gaps out of status.
- Another 78 replies came after a question, 35 after a finish, 21 after a delivery and 20 after a list of items waiting on the owner. Those stops carry something to decide.
- `AGENTS.md` Working rules says to stop only on a stop trigger. It does not say when a session may end its turn.

## Options considered

1. **A rule: no stop on a status update (recommended).** For: removes stops that leave nothing to decide; one line; the retro counts these stops, so the effect can be measured. Against: a session may run past a problem it should have raised; long runs are harder to follow.
2. **Stop only when something waits on the owner.** For: each stop carries a decision or a result. Against: stricter, so more risk of running on; a session must judge what waits on the owner.
3. **Leave it.** For: nothing to maintain; a status stop is a free check-in. Against: about 10 hours of gaps continue and the owner stays the one who restarts the work.

## Why

A status update gives the owner nothing to decide, so the stop costs attention and returns none.

## Consequences

- If accepted: `AGENTS.md` Working rules gains a line, and the `Decisions` row goes in `docs/process.md`. The retro skill counts status stops, so the next retro shows the effect.
- Not built by this ADR: any check that a session obeyed the rule.

## Source

Written 2026-11-23 by the session that built the retro skill. Retro page: `.scratch/retro/report.json`, finding F1. Facts: `waiting.reply.by_kind` in `.scratch/retro/facts.json`. Owner answer, 2026-11-23: option `keep-going-rule`.
