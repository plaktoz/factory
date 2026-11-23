---
name: retro
description: Read the task records in docs/retro/ (time, waiting on the owner, decisions, tokens, commands) and write a retro report as Markdown and HTML, with findings, options with pros and cons, and a prompt to paste back. Use when the owner asks for a retro, asks where supervision or admin time goes, or wants fewer decisions and less waiting.
---

Turn the task records into a report the owner reads in one sitting. The goal behind every retro: **less supervision, fewer stops for the owner, more time on the product.** A finding earns its place only if a change could move one of those.

The script computes the facts. You write the judgment. The renderer refuses a finding that cites a number the facts do not hold.

## Steps

1. **Refresh the records.** From the repo root run `python3 -I scripts/task-record.py write` for this branch, so its file is current. For a retro over past work, the records are the files already in `docs/retro/`. Done when `docs/retro/` lists a record for every branch you are asked to cover.
2. **Make the facts.** Run `python3 -I scripts/task-record.py facts docs/retro --out .scratch/retro/facts.json`. Create `.scratch/retro/` first. The file holds `facts`, `signals` (named findings that fired on a number) and a record count. Done when it prints the record and signal counts.
3. **Read every signal.** Each signal names what fired and the numbers behind it. Read the signal's section in the HTML page too (`python3 -I scripts/task-record.py report docs/retro --html .scratch/retro/data.html`). Done when you can say, for each signal, what a person would notice if it were fixed.
4. **Check the signal before you believe it.** A signal is a lead. Look at the transcripts or the repo for the fact it rests on, by running something, not by recalling. Examples: run the command a slow-call signal names; read the three longest question waits; read the last message before a run of status gaps. Done when each finding you keep has one fact you checked, and each one you drop has the reason in one line.
5. **Write `report.json`** in `.scratch/retro/`, to the schema below. One finding per change the owner could choose. Take a finding from a signal, or write `"signal": "judgment"` when you saw it in the data yourself. Done when every finding has 2 to 4 options, one recommended, and each option lists real pros and real cons.
6. **Render.** Run `python3 -I .claude/skills/retro/scripts/render.py .scratch/retro/report.json .scratch/retro/facts.json`. It writes `report.md` and `report.html` beside the JSON and exits 1 with every problem it finds. Done when it prints the finding count and exits 0.
7. **Look at the page.** Open `report.html`. Check that the table of findings, each evidence number and the prompt at the end read right. Done when you have looked, not when the render passed.
8. **Hand over** the path of both files and one line per finding in the owner's words. Say what the data could not show. Then wait for the pasted prompt.
9. **Apply the pasted prompt.** Each line names a finding and an option id. Apply each as `AGENTS.md` says: a reversible choice is a line in `docs/decisions.md`; a change to a rule the owner set, or to a `Decisions` row, is a `proposed` ADR. A line marked `NOT SURE` is answered, not applied.

## What counts as a finding

Rank by how much it cuts supervision, not by how large the number is.

- **Stops without asking.** The agent ends a turn with a status update, a finish or a delivery and the owner has nothing to decide. Each is a stop that a rule can remove.
- **The same question again.** A theme asked on several days, mostly answered with the recommendation. The fix is a default rule, so the question stops coming.
- **Open questions inflating a wait.** A few questions left unanswered for hours hold most of the total. The total is not a supervision cost. Report the capped figure.
- **Admin that does not move the product.** Records, task-list upkeep, decision pages, checks and chained delivery commands, set against product and spec work.
- **Machine waits.** Sleeps, monitors and polling that a script or a longer interval would cut.
- **Hooks and slow calls.** Charge only a command's own time. A call chained with others is not the hook's cost.

A number that is large but not caused by anyone's choice (time away, a test suite that takes minutes) is not a finding. Name it under limits or drop it.

## Schema

```json
{
  "title": "Retro: <period>",
  "intro": "One sentence on what the retro covers.",
  "period": "2026-11-14 to 2026-11-22",
  "storage_key": "unique-per-retro",
  "limits": ["What the data cannot show, one line each. At least one."],
  "findings": [{
    "id": "F1", "title": "What is wrong, in the owner's words",
    "category": "supervision | decisions | admin | waiting | tooling",
    "impact": "high | medium | low",
    "signal": "an id from facts.json signals, or judgment",
    "trigger": "reopens-decision | changes-scope | costly-to-reverse | no-clear-winner | routine",
    "trigger_detail": "One sentence: which rule it changes, or why it is routine.",
    "evidence": [{"fact": "waiting.reply.by_kind.status.n", "label": "replies after a status update"}],
    "today": "What the owner sees now, with one real number.",
    "after": "What the owner would see after the recommended option.",
    "options": [{
      "id": "kebab-id", "name": "Short label", "recommended": true,
      "see": "What the owner will notice, one sentence, no builder words.",
      "asks": "What it asks of the owner, or nothing.",
      "pros": ["..."], "cons": ["..."]
    }],
    "why": "Why the recommended option, one sentence."
  }]
}
```

Each `evidence.fact` is a dotted path into `facts` in `facts.json`. The renderer looks it up and prints the value, and refuses a path that is not there.

## Rules the renderer enforces

Tests: `scripts/test_render.py`. Each finding has an impact, a trigger from the stop triggers (or `routine`) with its detail, at least one evidence line that resolves, a `signal` that fired or `judgment`, 2 to 4 options, exactly one recommended, and at least one pro and one con per option. The report has at least one limit. `see` holds no builder word. Text cannot close the page's script tag.

## Writing findings

- **Say what changes for the owner.** "Sessions stop after a status update 144 times" beats "adjust stop conditions".
- **Report the capped number beside any total that a few long waits dominate.**
- **Options differ in kind.** Leave-as-is is an option when it is the honest alternative.
- **Cons are real.** A rule that cuts stops also lets a session run past a real problem. Say so.
- **A repeated question gets a default, and a default needs a veto.** Offer the one-line undo in `docs/decisions.md`.
- **Do not turn the owner's time into a score.** Reply waits include reading and thinking. Say which part is a stop the agent chose and which part is not.

## Prompt format

The page ends with one line per finding: `F1 <title>: <option name> [<option id>] (recommended)` or `(not the recommendation)`, with `Note:` for the owner's text and `NOT SURE. Question:` when unsure. This matches the decision-page format, so `task-record.py` counts the owner's answers the same way.
