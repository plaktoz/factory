---
name: decision-page
description: Turn open decisions into a one-file HTML page the user answers in one sitting (each card shows today, after, a preview and what each option changes for them), whose button builds a prompt to paste back. Use when decisions need the user's call, a review finds choices only they can make, or the user asks for "the html format".
---

Put each open decision on a page the user answers in one sitting, then act on the pasted prompt. Write every card from the **user's side**: what they see or do now, and what they would see or do after. How it is built is secondary, one line behind "How it works".

## Where the page lives, and why nothing may stay only on it

The page (`<name>.json` and the `<name>.html` rendered from it) is created in **`.scratch/`**. That folder is gitignored, so the page is a working copy: it is never committed, and anything that exists only on it is lost when the worktree goes. The record of a decision is therefore an **ADR in `docs/adr/`** and its follow-up work is a **task in `docs/tasks.md`**, both tracked.

**Both are written at the moment a decision is made, not later.** That moment is when the user's answer arrives: the pasted prompt, or an answer given in chat. Do not defer them to the end of the session, to "once the rest are answered", or to another turn. Do them before you do anything else with that answer. Once every card is closed (step 9), remove the page.

## Steps

1. **Triage first.** Work through every finding yourself. Fix what a check can settle (run it, show the output). Apply the recommended option yourself, and log it as "decided at recommendation, reversible", unless the choice reopens a recorded decision or an ADR, changes scope or phase, costs a lot to reverse, or has no option that is clearly better. A finding the spec already answers is a build task, not a card. If a finding needs a machine or login you do not have, make it a task. Keep for the page only what is left. Done when each finding is fixed with evidence, applied at the recommendation, made a task or listed as a decision. If nothing is left, do not build a page.
2. **Check facts before writing options.** A fact in a card (a tool, a flag, a file, what a run does) is looked up by running something (`--help`, a probe, a test run), not remembered or read off the source. Done when every factual claim has a command behind it, and a claim you only read in code says so on the card.
3. **Write `decisions.json`** to the schema below, in `.scratch/<name>.json` (create the folder if it is missing). Never write the page under `docs/`: it would be tracked, and the ADR is the record.
4. **Read it as an outsider.** For each option, answer from its `see` and `asks` alone: what changes for someone who has never seen the codebase? If you cannot, rewrite the card. Done when every option passes.
5. **Render.** Run `python3 -I .claude/skills/decision-page/scripts/render.py .scratch/<name>.json`. It validates the JSON, refuses builder words in `see` and unexplained ids in the question, today and after, writes `<name>.html` beside it, and exits non-zero on any problem. Done when it prints the card count and exits 0.
6. **Prove the page works** with `node .claude/skills/decision-page/scripts/check.mjs .scratch/<name>.html` (needs `puppeteer`; see the script header). It checks each card's question, Today and After, preview, and options, then clicks an option, writes a note, generates the prompt, reloads, and fails if a choice is lost. Done when it prints `ALL CHECKS PASSED`.
7. **Hand over** the path and one line per decision, in the user's words, and say the page is in `.scratch` and is removed once its decisions are recorded. Then wait.
8. **Close each decision the moment it is answered.** Each line of the pasted prompt names a decision and an option id. For every line, in this order and before moving to the next line or the next piece of work:
   1. **Apply** the option to the spec or code, and keep related sections consistent.
   2. **Backfill the ADR** (below). One ADR per decision, written now.
   3. **Create the task** (below). One task per decision, created now, even when the work is already done.
   4. **Commit** the ADR and the task entry, following the trailer rules in `AGENTS.md` (`Agent-Run:`, and `Decision: <adr id>` because the commit writes a decision). Do not push unless asked.

   A line marked `NOT SURE` is not made yet. Answer the question, and do not apply the option. Preserve it anyway: write the ADR with `status: proposed` (the options, what each costs, the user's question and your answer, no `Decision` yet) and create a task that says it waits on the user. That card is not closed, so the page stays. When the user decides, finish the same ADR (`status: accepted`, add the Decision and Why) in place and update its task.
9. **Remove the page only when every card is closed.** A card is closed when all of these are true, each checked by looking, not remembered: the option is applied (or, for `NOT SURE`, answered and waiting with a `proposed` ADR); `docs/adr/<date>-<slug>.md` exists and names the decision id and the option id; `docs/tasks.md` has the task and names that ADR file; both are committed (`git status` shows nothing for them); and `python3 -I scripts/docs-check/records.py .` prints `0 problem(s)`. If any card fails a check, fix it, and keep the page. If any card is still `NOT SURE`, keep the page. Then `rm .scratch/<name>.json .scratch/<name>.html` (plain `rm`: they are untracked). Report each decision with its ADR and task, then the removal. Done when `.scratch/<name>.*` is gone and nothing in the repo points at it as the only copy.

## ADR backfill

Look at two or three recent files in `docs/adr/` (for example `2026-11-20-which-engine-serves-each-repo.md`) before writing, so this skill's template never drifts from what the project does. The format at the time of writing:

- **File name** `docs/adr/<YYYY-MM-DD>-<slug>.md`, today's date, a kebab-case slug of the decision, never a counter. The ADR's id is the file name without `.md`.
- **Front matter**: `scope: repo`, `repo: <this repo's name>`, `topic: <the slug>`, `status: accepted` (or `proposed` for `NOT SURE`), `supersedes: []` (list the id of any ADR this reverses; never edit another author's ADR, write a new one that supersedes it).
- **Sections**, in this order: `# <title as a statement>`; `## Decision` (who accepted it and when, which decision id and option id on which page, then what now holds); `## Context` (what was true, with facts you checked by running something); `## Options considered` (every option, recommended one marked, each with For and Against); `## Why`; `## Consequences` (what changes, what is not built by this ADR, and the task that builds it); `## Source` (when and by whom it was written; the page name and decision id as `.scratch/<name>.json`, decision `D1`).
- **It must stand without the page.** The page is deleted, so copy in each option that was not chosen and why. A reader who only has the ADR can see what was turned down.
- **Do not write `docs/decision-pages/...` paths.** That folder is not where pages live now.

## Task

The follow-up task goes in **`docs/tasks.md`**, which is where this project keeps its durable state. Do not invent another list.

- Add a numbered item to the "Not done" list (style of the existing items), and a dated line in the Log. The ADR file name must appear in `docs/tasks.md` (`records.py` fails otherwise).
- The item says: the owner's decision and date, the ADR file name, the option chosen; what to change, in files and functions; how to check it (the test, or the command); and what is not built yet.
- If the option is already applied in the same turn, the item is a `[x]` with the evidence (test name, commit, command output) and the Log line says so. If it is not built, it is `[ ]` and says "not built". If the decision needs no build work, the item says so in one line; do not skip the item.

## Schema

```json
{
  "title": "Page title",
  "intro": "One sentence on what is already fixed and what is asked.",
  "target": "docs/design/modules/09-worker-adapters-and-governed-helpers.md",
  "storage_key": "unique-per-page",
  "decisions": [{
    "id": "D1", "title": "Short noun phrase", "ref": "Where it lands (module, section)",
    "question": "The question the user would ask, in their words?",
    "today": "What the user sees or does now, with one real fact from their project.",
    "after": "What the user would see or do after the recommended option.",
    "preview": "The screen, file listing, PR check or message they would see. Plain text, shown as-is.",
    "options": [{
      "id": "kebab-id", "name": "Short label", "recommended": true,
      "see": "What you'll see or do differently, one sentence, no builder words.",
      "asks": "What it asks of the user (a setting, a habit, a one-time rename), or \"nothing\".",
      "how": "Optional. How it works, one line. Shown folded.",
      "pros": ["..."], "cons": ["..."]
    }],
    "why": "Why the recommended option, one sentence."
  }]
}
```

Rules the renderer enforces: unique ids; exactly one recommended option per decision; 2 to 4 options; at least one pro and one con each; every text field non-empty; `question` ends with `?`; `see` holds no builder word (script, module, schema, JSON, flag, function and the like); `question`, `today` and `after` name no id such as `D1` or `module 8` that is not a card on the page. "Not sure" is added to every card by the page. A page in the old shape (one `context`, no `see` or `asks`) still renders, with a warning, so answered pages stay readable.

## Writing decisions

- **Question first.** The card opens with what the user would ask ("When you read 'per D1', how do you know which decision it is?"), not a topic label.
- **Today is real.** Quote one fact from their project in `today`: a stale line, a number, a file name, a message they would get.
- **Preview is concrete.** Show the thing itself: the message text, the PR line, the file list. Not a description of it.
- **Plain words.** Define each technical term where it first appears, or cut it. An internal id carries its meaning beside it.
- **Options differ in kind.** Two options that are the same choice with a different amount are one option.
- **Cons are real.** An option with a strong recommendation still lists what it costs.
- **Order by recommendation**, recommended first.
- A decision the user already answered (in the spec, an ADR or this session) is not asked again.

## Prompt format

The page produces one line per decision: `D3 <title>: <option name> [<option id>] (recommended)` or `(not the recommendation)`, with `Note:` for the user's text and `NOT SURE. Question:` when unsure. Do not change this format; step 8 parses it by eye and the check script asserts it.
