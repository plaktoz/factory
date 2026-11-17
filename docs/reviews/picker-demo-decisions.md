# Picker demo: notes

Page: `docs/reviews/picker-demo-decisions.html`. Data: `docs/reviews/picker-demo-decisions.json`.

A demo of the user-side card shape from the `decision-page` skill (2026-11-17), built on three real problems in this repo. **Nothing on it was answered and nothing is applied.** The table names the recommended option only so `records.py` can read it; it is not an owner's answer.

| Decision | Choice | Recommended? | Applied in |
| --- | --- | --- | --- |
| P1 Decision ids that mean one thing | `name-in-text` (not an answer) | Yes | Not applied |
| P2 Where a new session picks up | `refresh-on-finish` (not an answer) | Yes | Not applied |
| P3 Who notices when the docs go wrong | `check-on-commit` (not an answer) | Yes | Not applied |

The three problems are real and still open: `D1` names three different decisions on three pages, the top of `docs/tasks.md` is a day behind `main`, and nothing runs `scripts/docs-check` except a person.
