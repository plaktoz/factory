# Decisions made at the recommendation

Reversible choices a session made without asking, one line each, newest first. To reverse one, tell a session "undo `<slug>`". A choice that meets a stop trigger is an ADR in `adr/`, not a line here. The rule is in `AGENTS.md`, under Working rules.

Line format, checked by `scripts/docs-check/records.py`:

`- YYYY-MM-DD \`slug\`: what was chosen, over what. Undo: how to reverse it.`

- 2026-11-22 `log-oldest-to-archive`: the oldest Log entry (task 33, 2026-11-21) moved to `docs/tasks-archive.md` unchanged, to keep the Log at 12 when this session's entry was added. Undo: move it back.
- 2026-11-22 `close-the-ticket-with-the-work`: a task is done only when its GitHub issue is closed, and a PR names it with `Closes #<n>` (owner instruction after #86 stayed open), over leaving closing to whoever notices. Undo: delete the bullet in `AGENTS.md` Working rules.
- 2026-11-22 `tasks-log-cap-12`: `docs/tasks.md` keeps the 12 newest Log entries, over 20 or no cap. Undo: change `LOG_CAP` in `records.py`.
- 2026-11-22 `archive-closed-items`: closed items, finished sections A to E and older Log entries moved to `docs/tasks-archive.md` unchanged, over deleting them. Undo: move them back.
