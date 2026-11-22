# docs-check

Checks the spec. Run from the repo root. Each script was shown to catch a planted fault.

| Script | Checks | Run |
| --- | --- | --- |
| `links.py` | Every relative link and anchor in `docs/` and `AGENTS.md` resolves | `python3 -I scripts/docs-check/links.py .` |
| `mermaid.mjs` | Every Mermaid block parses | `MERMAID_NODE_MODULES=<folder with mermaid and jsdom> node scripts/docs-check/mermaid.mjs $(grep -l '```mermaid' docs/design/*.md docs/design/*/*.md)` |
| `spec-contracts/` | The engine's dataclasses and schemas match the spec (field names and order; every YAML and JSON example validates). See its README | `cd factory/engine && uv run --group dev pytest ../../scripts/docs-check/spec-contracts` |
| `contracts.py` | Each name in a module's "Depends on" is defined by the upstream module | `python3 -I scripts/docs-check/contracts.py .` |
| `records.py` | Decision pages (`docs/decision-pages/*.json`, if any) match their records; each ADR is named in `docs/tasks.md` once it is dated 2026-11-16 or later; `docs/tasks.md` names a recent `main` sha does not call a merged PR open or blocked; `docs/reviews/` does not exist and `docs/tasks.md` does not name it | `python3 -I scripts/docs-check/records.py .` |
| `records.py`, checks 7 and 8 | The Log in `docs/tasks.md` has at most 12 entries (older ones go to `docs/tasks-archive.md`); each line of `docs/decisions.md` has a date, a slug and an `Undo:` | (same command) |
| `records.py`, check 9 | A pull request merged since 2026-11-22 does not name an open issue in its title, so a finished ticket is closed. Needs `gh`; it is skipped with a note when `gh` cannot answer. Its logic is `issue_close.py`, tested by `test_issue_close.py` | `python3 -I scripts/docs-check/records.py .` (the logic's tests: `python3 -m pytest scripts/docs-check/test_issue_close.py`) |
| `../code-share.py` | Share of commits that touch `factory/` (target above 60%), ADRs per day, and choices logged in `docs/decisions.md`. A report, not a check: it always exits 0 | `python3 -I scripts/code-share.py [days]` |
| `criteria.py` | Per-module count of ticked and open acceptance criteria; pass a module number to list the open ones | `python3 -I scripts/docs-check/criteria.py . [module]` |

Known result: `contracts.py` reports `11 | depends on 3.dashboard_url`. That is a config key in parentheses in module 11's list, not a function, so it is not a gap.

