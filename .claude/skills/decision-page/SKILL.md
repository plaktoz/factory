---
name: decision-page
description: Turn open decisions into a one-file HTML page the user answers in one sitting (each card shows today, after, a preview and what each option changes for them), whose button builds a prompt to paste back. Use when decisions need the user's call, a review finds choices only they can make, or the user asks for "the html format".
---

Put each open decision on a page the user answers in one sitting, then act on the pasted prompt. Write every card from the **user's side**: what they see or do now, and what they would see or do after. How it is built is secondary, one line behind "How it works".

## Where the page lives, and why nothing may stay only on it

The page (`<name>.json` and the `<name>.html` rendered from it) is created in **`.scratch/`**. That folder is gitignored, so the page is a working copy: it is never committed, and anything that exists only on it is lost when the worktree goes. The record of a decision is therefore a **`Decisions` row in the spec** it belongs to (`docs/process.md` for how this repo is built), and its follow-up work is a **task in `docs/tasks.md`**, both tracked. A card that is not answered yet is a `proposed` ADR in `docs/adr/`.

**Both are written at the moment a decision is made, not later.** That moment is when the user's answer arrives: the pasted prompt, or an answer given in chat. Do not defer them to the end of the session, to "once the rest are answered", or to another turn. Do them before you do anything else with that answer. Once every card is closed (step 9), remove the page.

## Steps

1. **Triage first.** Work through every finding yourself. Fix what a check can settle (run it, show the output). A bug fix or record upkeep is a commit, not a card. Apply the recommended option yourself and add one line to `docs/decisions.md`, unless the choice meets a **stop trigger** in `AGENTS.md` (Working rules). A finding the spec already answers is a build task, not a card. If a finding needs a machine or login you do not have, make it a task. Keep for the page only the stop triggers, at most one page a day and at most five cards (`render.py` refuses a sixth); decide the rest at the recommendation and log them. Done when each finding is fixed with evidence, logged in `docs/decisions.md`, made a task, or listed as a card with its `trigger`. If nothing is left, do not build a page.
2. **Check facts before writing options.** A fact in a card (a tool, a flag, a file, what a run does) is looked up by running something (`--help`, a probe, a test run), not remembered or read off the source. Done when every factual claim has a command behind it, and a claim you only read in code says so on the card.
3. **Write `decisions.json`** to the schema below, in `.scratch/<name>.json` (create the folder if it is missing). Never write the page under `docs/`: it would be tracked, and the record is a `Decisions` row in the spec (or a `proposed` ADR while the card waits).
4. **Read it as an outsider.** For each option, answer from its `see` and `asks` alone: what changes for someone who has never seen the codebase? If you cannot, rewrite the card. Done when every option passes.
5. **Render.** Run `python3 -I .claude/skills/decision-page/scripts/render.py .scratch/<name>.json`. It validates the JSON, refuses builder words in `see` and unexplained ids in the question, today and after, writes `<name>.html` beside it, and exits non-zero on any problem. Done when it prints the card count and exits 0.
6. **Prove the page works** with `node .claude/skills/decision-page/scripts/check.mjs .scratch/<name>.html` (needs `puppeteer`; see the script header). It checks each card's question, Today and After, preview, and options, then clicks an option, writes a note, generates the prompt, reloads, and fails if a choice is lost. Done when it prints `ALL CHECKS PASSED`.
7. **Hand over** the path and one line per decision, in the user's words, and say the page is in `.scratch` and is removed once its decisions are recorded. Then wait.
8. **Close each decision the moment it is answered.** Each line of the pasted prompt names a decision and an option id. For every line, in this order and before moving to the next line or the next piece of work:
   1. **Apply** the option to the spec or code, and keep related sections consistent.
   2. **Fold the decision** (below). The `proposed` ADR for the card becomes a `Decisions` row, and the ADR file is deleted in the same commit. If no ADR exists yet, write none: add the row.
   3. **Record it in the task list** (below): a Log line, and an item only when work is left. A session does not edit `docs/tasks.md` (`AGENTS.md`): the Log line and the item go in the pull request's `## Task record`, and the merger pastes them in. The session that merges edits the file.
   4. **Commit** the row and the deletion (the task entry is in the pull request body, step 3), following the trailer rules in `AGENTS.md` (`Agent-Run:`, and `Decision: <id>` because the commit writes a decision). Do not push unless asked.

   A line marked `NOT SURE` is not made yet. Answer the question, and do not apply the option. Preserve it anyway: write the ADR with `status: proposed` (the options, what each costs, the user's question and your answer, no `Decision` yet) and create a task that says it waits on the user. That card is not closed, so the page stays. When the user decides, fold it as in step 2 and update its task.
9. **Remove the page only when every card is closed.** A card is closed when all of these are true, each checked by looking, not remembered: the option is applied (or, for `NOT SURE`, answered and waiting with a `proposed` ADR); the spec has a `Decisions` row whose Rule and Id cells name the decision and the option, and no accepted ADR file is left in `docs/adr/`; the pull request's `## Task record` names the decision id (in a Log line, and in an item if work is left), or, in the merge session, `docs/tasks.md` does; the row and the deletion are committed (`git status` shows nothing for them); and `python3 -I scripts/docs-check/records.py .` prints `0 problem(s)`. If any card fails a check, fix it, and keep the page. If any card is still `NOT SURE`, keep the page. Then `rm .scratch/<name>.json .scratch/<name>.html` (plain `rm`: they are untracked). Report each decision with its ADR and task, then the removal. Done when `.scratch/<name>.*` is gone and nothing in the repo points at it as the only copy.

## Fold the decision

An accepted decision is a row, not a file. Add one row to the `## Decisions` table at the end of the module file it belongs to (`docs/design/shared/` or `docs/design/phase-2.md` for those; `docs/process.md` for how this repo is built): **Rule** (what now holds), **Why** (the fact it rests on), **Not chosen** (each option that was turned down, in a few words), **Id** (`<date>-<slug>`, then the decision id and option id, such as `D3 fix-the-words`). Each cell is about 35 words. Make sure the spec's body states the rule too, and delete the `proposed` ADR file. The full options text stays in git.

## Proposed ADR (for a card that is not answered)

Use this only for a `NOT SURE` line or a stop trigger waiting for the owner. Look at a `proposed` file in `docs/adr/` before writing, so this skill's template never drifts from what the project does. The format at the time of writing:

- **File name** `docs/adr/<YYYY-MM-DD>-<slug>.md`, today's date, a kebab-case slug of the decision, never a counter. The ADR's id is the file name without `.md`.
- **Front matter**: `scope: repo`, `repo: <this repo's name>`, `topic: <the slug>`, `status: proposed`, `supersedes: []` (list the id of any ADR this reverses; never edit another author's ADR, write a new one that supersedes it).
- **Sections**, in this order: `# <title as a statement>`; `## Decision` (the question, the recommended option, and what holds if the owner accepts it); `## Context` (what was true, with facts you checked by running something); `## Options considered` (every option, recommended one marked, each with For and Against); `## Why`; `## Consequences` (what changes, what is not built by this ADR, and the task that builds it); `## Source` (when and by whom it was written; the page name and decision id as `.scratch/<name>.json`, decision `D1`).
- **It must stand without the page.** The page is deleted, so copy in each option that was not chosen and why. A reader who only has the ADR can see what was turned down.
- **Do not write `docs/decision-pages/...` paths.** That folder is not where pages live now.

## Task

The follow-up task goes in **`docs/tasks.md`**, which is where this project keeps its durable state. Do not invent another list. A session writes it in its pull request's `## Task record`, and whoever merges the pull request pastes it into `docs/tasks.md`; a session does not edit that file itself.

- Add a dated line in the Log, and a numbered item to the "Not done" list when work is left. The Log line names the decision id (and the ADR file name, while it is still `proposed`).
- The item says: the owner's decision and date, the decision id, the option chosen; what to change, in files and functions; how to check it (the test, or the command); and what is not built yet.
- If the option is already applied in the same turn, or needs no build work, skip the numbered item: the Log line names the decision id and the evidence (test name, commit, command output). If work is left, the item is `[ ]` and says "not built".

## Schema

```json
{
  "title": "Page title",
  "intro": "One sentence on what is already fixed and what is asked.",
  "target": "docs/design/modules/09-worker-adapters-and-governed-helpers.md",
  "storage_key": "unique-per-page",
  "decisions": [{
    "id": "D1", "title": "Short noun phrase", "ref": "Where it lands (module, section)",
    "trigger": "reopens-decision | changes-scope | costly-to-reverse | no-clear-winner",
    "trigger_detail": "One sentence: which decision it reopens, what scope moves, what is costly to undo, or why no option wins.",
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

Rules the renderer enforces (tests: `scripts/test_render.py`): each card has a `trigger` from the four stop triggers and a non-empty `trigger_detail`, shown on the page as "Asked because"; unique ids; exactly one recommended option per decision; 2 to 4 options; at least one pro and one con each; every text field non-empty; `question` ends with `?`; `see` holds no builder word (script, module, schema, JSON, flag, function and the like); `question`, `today` and `after` name no id such as `D1` or `module 8` that is not a card on the page. "Not sure" is added to every card by the page. A page in the old shape (one `context`, no `see` or `asks`) still renders, with a warning, so answered pages stay readable.

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
