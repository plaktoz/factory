# Docs

| Folder | Holds |
| --- | --- |
| `design/` | Specs. `phase-1.md` is the overview and index. `modules/` has one file per module, `shared/` the cross-cutting sections, and `phase-2.md` tracks what moved out of phase 1. |
| `adr/` | Decisions made while building, named `<date>-<slug>.md`, never by a counter. Each starts with YAML front matter (`scope`, `repo`, `topic`, `status`, `supersedes`); the rule is in `AGENTS.md`, under Working rules. |
| `decision-pages/` | Source (`*.json`) and generated `*.html` for decision pages the owner answers in one sitting. Empty until the next page; each answer then becomes an ADR in `adr/`. |
| `setup/` | Step-by-step setup for a piece of work the owner runs by hand, such as [the spec workflow pilot](setup/spec-workflow-pilot.md). |
| `tasks.md` | The task list and its state. Read "Resume here" to continue the work from the file alone. |
| `approvals.md` | Standing owner approvals and whether each was carried through to every doc and task. |
| `research/` | Primary-source notes, such as CLI flags and output formats. |

Some ADRs cite files under `docs/reviews/`. That folder no longer exists; its last commit is `746ec67`. To read an old path, run `git ls-tree -r --name-only 746ec67 docs/reviews` to find it, then `git show 746ec67:<path>`. Do not edit those ADRs to fix the paths; see `AGENTS.md`.

Change the spec in the same commit as the code that changes the behavior.

Format: markdown only, with diagrams as Mermaid blocks. Do not commit `.docx` or `.pdf` copies of a spec; see `adr/2026-11-14-markdown-as-spec-format.md`.
