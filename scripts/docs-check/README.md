# docs-check

Checks the spec. Run from the repo root. Each script was shown to catch a planted fault.

| Script | Checks | Run |
| --- | --- | --- |
| `links.py` | Every relative link and anchor in `docs/` and `AGENTS.md` resolves | `python3 -I scripts/docs-check/links.py .` |
| `mermaid.mjs` | Every Mermaid block parses | `MERMAID_NODE_MODULES=<folder with mermaid and jsdom> node scripts/docs-check/mermaid.mjs $(grep -l '```mermaid' docs/design/*.md docs/design/*/*.md)` |
| `contracts.py` | Each name in a module's "Depends on" is defined by the upstream module | `python3 -I scripts/docs-check/contracts.py .` |

Known result: `contracts.py` reports `11 | depends on 3.dashboard_url`. That is a config key in parentheses in module 11's list, not a function, so it is not a gap.
