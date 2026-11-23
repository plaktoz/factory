---
scope: repo
repo: factory
topic: cap-a-decision-page-at-five-cards
status: proposed
supersedes: []
---

# A decision page holds at most five cards

## Decision

Question for the owner: should the "one decision page a day" rule in `AGENTS.md` also cap a page at five cards, with every other finding decided at the recommendation and logged?

Recommended option: **triage before a page and cap it at five cards.** You chose this on the retro page (finding F4, 2026-11-23). It changes a rule the owner set, so it waits here until you accept it.

## Context

- Answers per day, from the transcripts: 14 on 2026-11-14, 5, 6, 3, 6, 1, then 39 on 2026-11-21 and 25 on 2026-11-22. The two batch days hold 64 of 99 answers.
- Those days came from decision pages with 8 cards each ("Item 1 of 8", "Decision 3 of 8" in the question text).
- The owner took the recommendation in 71 of 89 answers (80%).
- `AGENTS.md` already says to stop only on a stop trigger, and the `decision-page` skill's first step is triage. The batch days suggest the triage step is not holding.

## Options considered

1. **Triage harder and cap the page at five cards (recommended).** For: smaller pages are answered faster; fits the "decide by default" rule. Against: a session decides more without the owner; five is a guess.
2. **Leave it.** For: many cards in one sitting can be efficient. Against: large batches keep arriving.

## Why

The working rules already say to stop only on a trigger. A cap makes the triage step visible, because a page that needs more than five cards has to say which ones are not triggers.

## Consequences

- If accepted: `AGENTS.md` Working rules gains the cap, step 1 of `.claude/skills/decision-page/SKILL.md` names it, and the retro counts answers per day so the effect shows.
- Not built by this ADR: a check in `render.py` that refuses a sixth card. That is a follow-up the owner can ask for.

## Source

Written 2026-11-23 by the session that built the retro skill. Retro page: `.scratch/retro/report.json`, finding F4. Facts: `decisions.per_day` in `.scratch/retro/facts.json`. Owner answer, 2026-11-23: option `triage-harder`.
