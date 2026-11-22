# Standing approvals

A permission to act: "do X once Y holds". A decision about how the system works is an ADR in `docs/adr/`, and a row here links to it and does not restate it. Put the permission here when you receive it, not only in a PR comment or a decision page. The session that receives it carries it through, and fills the last column when every doc and task it touches is updated. A row stays after it is done, as the record of who allowed what.

| Date | Permission | Decision it rests on | Carried through |
| --- | --- | --- | --- |
| 2026-11-14 | Run every wave to the end with test evidence. A checkpoint is a commit, push and merge without asking. At most 3 passes per issue. | `docs/tasks.md`, Rules from the owner | yes |
| 2026-11-15 | Merge PR #43 once its conflict is resolved and the D7 record is on `main`. | D7, `docs/design/modules/09-worker-adapters-and-governed-helpers.md`, "Threat model and isolation" | yes, merged as `683e3e5` on 2026-11-16 |
| 2026-11-22 | A session pushes its own branch and opens its pull request when the work is done, and merges `origin/main` into the branch just before the push. Reversible choices are decided at the recommendation and logged in `docs/decisions.md`. | `docs/adr/2026-11-22-decide-by-default-and-scale-the-record.md` | yes, in `AGENTS.md` (Working rules) on branch `plaktoz/decide-by-default` |
| 2026-11-16 | Apply the process fixes: this table, follow-through by the deciding session, the stale-PR check in `records.py`, no "No commits" rule, a project `.claude/settings.json` allowlist. | owner reply in the session | yes, in `b2e64a8` |
