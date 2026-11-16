# Standing approvals

Each row is an owner approval that other work depends on. Put an approval here when you receive it, not only in a PR comment or a decision page. The session that receives it carries it through, and ticks the last column when every doc and task it touches is updated. `scripts/docs-check/records.py` does not read this file; the check is by hand.

| Date | Approval | Source | Carried through |
| --- | --- | --- | --- |
| 2026-11-14 | Run every wave to the end with test evidence; a checkpoint is a commit, push and merge without asking. At most 3 passes per issue. | `docs/tasks.md`, Rules from the owner | yes |
| 2026-11-15 | Keep the history, including commit `6a6ff04`; no force push (D1). | `docs/reviews/wave3-open-decisions.md` | yes |
| 2026-11-15 | Both Codex sandbox changes are accepted for Codex workers only (D7). | `docs/reviews/pr43-codex-decisions.md`, module 9 "Threat model and isolation" | yes, on `main` as PR #48 |
| 2026-11-15 | Merge PR #43 once its conflict is resolved and the D7 record is on `main`. | PR #43 comment | yes, merged as `683e3e5` on 2026-11-16 |
| 2026-11-16 | Add this table, make the deciding session own follow-through, add the stale-PR check to `records.py`, remove the "No commits unless the owner asks" rule, and add a project `.claude/settings.json` allowlist. | owner reply in the session | yes, in the commit that adds this file |
