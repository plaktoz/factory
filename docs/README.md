# Docs

| Folder | Holds |
| --- | --- |
| `design/` | Specs. `phase-1.md` is the overview and index. `modules/` has one file per module, `shared/` the cross-cutting sections, and `phase-2.md` tracks what moved out of phase 1. Each module file ends with a `Decisions` table. |
| `process.md` | How this repo is built: the rules for sessions, the pilot and the checks, each with its why. |
| `adr/` | Proposed decisions only, named `<date>-<slug>.md`. An accepted ADR is folded into a spec's `Decisions` table and its file deleted; `adr/README.md` names the commit that holds the full text. The rule is in `AGENTS.md`, and `process.md` gives the reasons. |
| `decision-pages/` | Source (`*.json`) and generated `*.html` for decision pages the owner answers in one sitting. Empty until the next page; each answer then becomes a `Decisions` row in a spec, or a `proposed` ADR in `adr/` while it waits. |
| `setup/` | Step-by-step setup for a piece of work the owner runs by hand, such as [the spec workflow pilot](setup/spec-workflow-pilot.md). |
| `tutorial.md` | A first run in a new project: install, `init`, `add`, `run`. |
| `tasks.md` | The task list and its state. Read "Resume here" to continue the work from the file alone. |
| `tasks-archive.md` | Closed items, finished sections and older Log entries moved from `tasks.md`, unchanged. History only. |
| `decisions.md` | Reversible choices a session made at the recommendation, one line each, with how to undo it. Skim it to veto. |
| `retro/` | One `<branch>.json` per task, made by `scripts/task-record.py write`: wall time, time waiting on the owner (turn, question and permission waits), decisions, tokens and lines by product, spec and process. A turn wait counts every gap before your next prompt, so it is an upper bound on approval time. `scripts/task-record.py report` totals the folder, and the `retro` skill (`.claude/skills/retro/`) reads it and writes a Markdown and HTML report with options and a prompt to paste back. |
| `approvals.md` | Standing owner approvals and whether each was carried through to every doc and task. |
| `research/` | Primary-source notes, such as CLI flags and output formats. |

Some folded ADRs cite files under `docs/reviews/`. That folder no longer exists; its last commit is `746ec67`. To read an old path, run `git ls-tree -r --name-only 746ec67 docs/reviews` to find it, then `git show 746ec67:<path>`. Read a folded ADR with the command in `adr/README.md`.

Change the spec in the same commit as the code that changes the behavior.

Format: markdown only, with diagrams as Mermaid blocks. Do not commit `.docx` or `.pdf` copies of a spec; see the first row of the `Decisions` table in `process.md`.
