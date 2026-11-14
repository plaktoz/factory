# Markdown is the spec format

Status: accepted, 2026-11-14

## Decision

The phase 1 spec is `docs/design/phase-1.md` and the module files it links (see `2026-11-14-one-file-per-module.md`). There is no `.docx` copy, and none is kept in step.

## Why

- Diffs and review: the markdown is 2,712 lines and diffs line by line. The docx is one 616 KB XML line inside a zip, so git cannot show what changed.
- Content parity: the docx held the same text, 34 tables and 6 images, with no comments, tracked changes, footnotes or headers. Its only extra was the six diagrams, which are now Mermaid in the markdown.
- Drift: the docx was already behind. It still carried `/dev/worktree`, "formats before each checkpoint", `%USERPROFILE%` paths, a registry and a "Clean up stale" button, all of which the review removed.
- Agents and tools: an agent can read and edit markdown directly. A docx needs conversion and cannot be edited safely in place.
- Cost: two formats mean every change is made twice, and one copy goes stale.

## Consequences

- Diagrams are Mermaid code blocks, so they are reviewed as text and render on GitHub.
- A Word or PDF copy for a reader outside the repo is generated from the markdown when needed and is not committed.
- Wireframes of screens are text tables.
