# Decisions made at the recommendation

Reversible choices a session made without asking, one line each, newest first. To reverse one, tell a session "undo `<slug>`". A choice that meets a stop trigger is an ADR in `adr/`, not a line here. The rule is in `AGENTS.md`, under Working rules.

Line format, checked by `scripts/docs-check/records.py`:

`- YYYY-MM-DD \`slug\`: what was chosen, over what. Undo: how to reverse it.`

- 2026-11-22 `tasks-log-cap-12`: `docs/tasks.md` keeps the 12 newest Log entries, over 20 or no cap. Undo: change `LOG_CAP` in `records.py`.
- 2026-11-22 `archive-closed-items`: closed items, finished sections A to E and older Log entries moved to `docs/tasks-archive.md` unchanged, over deleting them. Undo: move them back.
