# Docs

| Folder | Holds |
| --- | --- |
| `design/` | Specs. `phase-1.md` is the source of truth for phase 1. |
| `adr/` | Decisions made while building, named `<date>-<slug>.md`, never by a counter. |
| `reviews/` | Review findings on the design, with what was fixed and what was decided. |
| `research/` | Primary-source notes, such as Codex usage output and CLI flags. |

Change the spec in the same commit as the code that changes the behavior.

Format: markdown only, with diagrams as Mermaid blocks. Do not commit `.docx` or `.pdf` copies of a spec; see `adr/2026-11-14-markdown-as-spec-format.md`.
