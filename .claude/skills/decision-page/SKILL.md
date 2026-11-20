---
name: decision-page
description: Turn open decisions into a one-file HTML page the user answers in one sitting (each card shows today, after, a preview and what each option changes for them), whose button builds a prompt to paste back. Use when decisions need the user's call, a review finds choices only they can make, or the user asks for "the html format".
---

Put each open decision on a page the user answers in one sitting, then act on the pasted prompt. Write every card from the **user's side**: what they see or do now, and what they would see or do after. How it is built is secondary, one line behind "How it works".

## Steps

1. **Triage first.** Work through every finding yourself. Fix what a check can settle (run it, show the output). Apply the recommended option yourself, and log it as "decided at recommendation, reversible", unless the choice reopens a recorded decision or an ADR, changes scope or phase, costs a lot to reverse, or has no option that is clearly better. A finding the spec already answers is a build task, not a card. If a finding needs a machine or login you do not have, make it a task. Keep for the page only what is left. Done when each finding is fixed with evidence, applied at the recommendation, made a task or listed as a decision. If nothing is left, do not build a page.
2. **Check facts before writing options.** A fact in a card (a tool, a flag, a file, what a run does) is looked up by running something (`--help`, a probe, a test run), not remembered or read off the source. Done when every factual claim has a command behind it, and a claim you only read in code says so on the card.
3. **Write `decisions.json`** to the schema below, in the repo's `docs/decision-pages/`.
4. **Read it as an outsider.** For each option, answer from its `see` and `asks` alone: what changes for someone who has never seen the codebase? If you cannot, rewrite the card. Done when every option passes.
5. **Render.** Run `python3 -I .claude/skills/decision-page/scripts/render.py docs/decision-pages/<name>.json`. It validates the JSON, refuses builder words in `see` and unexplained ids in the question, today and after, writes `<name>.html` beside it, and exits non-zero on any problem. Done when it prints the card count and exits 0.
6. **Prove the page works** with `node .claude/skills/decision-page/scripts/check.mjs docs/decision-pages/<name>.html` (needs `puppeteer`; see the script header). It checks each card's question, Today and After, preview, and options, then clicks an option, writes a note, generates the prompt, reloads, and fails if a choice is lost. Done when it prints `ALL CHECKS PASSED`.
7. **Hand over** the path and one line per decision, in the user's words. Then wait.
8. **Apply the pasted prompt.** Each line names a decision and an option id. Apply it to the spec or code, keep related sections consistent, and record the choices in `docs/decision-pages/<name>.md`. A line marked `NOT SURE` gets an answer and waits for the user before it is applied.

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
