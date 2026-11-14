---
name: decision-page
description: Turn open design decisions into a one-file HTML page (context, options with pros and cons, a question box per decision) whose button builds a prompt to paste back. Use when decisions need the user's call, a review finds choices only they can make, or the user asks for "the html format".
---

Put each open decision on a page the user answers in one sitting, then act on the pasted prompt.

## Steps

1. **Triage first.** Work through every finding yourself. Fix what a check can settle (run it, show the output). Apply the recommended option yourself, and log it as "decided at recommendation, reversible", unless the choice reopens a recorded decision or an ADR, changes scope or phase, costs a lot to reverse, or has no option that is clearly better. If a finding needs a machine or login you do not have, make it a task, not a card. Keep for the page only what is left. Done when each finding is fixed with evidence, applied at the recommendation, made a task or listed as a decision. If nothing is left, do not build a page.
2. **Check facts before writing options.** An option's pro or con that states a fact about a tool, flag or file is looked up (`--help`, a probe, a test run) and not remembered. Done when every factual claim in the decisions has a command behind it.
3. **Write `decisions.json`** to the schema below, in the repo's `docs/reviews/`.
4. **Render.** Run `python3 -I .claude/skills/decision-page/scripts/render.py docs/reviews/<name>.json`. The script validates the JSON, writes `<name>.html` beside it and exits non-zero on any problem. Done when it prints the card count and exits 0.
5. **Prove the page works** with `node .claude/skills/decision-page/scripts/check.mjs docs/reviews/<name>.html` (needs `puppeteer`; see the script header). It clicks an option, writes a note, generates the prompt, reloads, and fails if a choice is lost. Done when it prints `ALL CHECKS PASSED`.
6. **Hand over** the path and a one-line summary per decision. Then wait.
7. **Apply the pasted prompt.** Each line names a decision and an option id. Apply it to the spec or code, keep related sections consistent, and record the choices in `docs/reviews/<name>.md`. A line marked `NOT SURE` gets an answer and waits for the user before it is applied.

## Schema

```json
{
  "title": "Page title",
  "intro": "One sentence on what is already fixed and what is asked.",
  "target": "docs/design/modules/09-worker-adapters-and-governed-helpers.md",
  "storage_key": "unique-per-page",
  "decisions": [{
    "id": "D1", "title": "Short noun phrase", "ref": "Where it lands (module, section)",
    "context": "What is true now and why it needs a call. Facts only, 1-3 sentences.",
    "options": [{
      "id": "kebab-id", "name": "What you would do", "recommended": true,
      "pros": ["..."], "cons": ["..."]
    }],
    "why": "Why the recommended option, one sentence."
  }]
}
```

Rules the renderer enforces: unique ids, exactly one recommended option per decision, 2 to 4 options, at least one pro and one con each, every text field non-empty. "Not sure" is added to every card by the page.

## Writing decisions

- **Minimal context.** State the fact and the consequence. Cut history and restating the spec.
- **Options differ in kind.** Two options that are the same choice with a different amount are one option.
- **Cons are real.** An option with a strong recommendation still lists what it costs.
- **Order by recommendation**, recommended first.
- A decision the user already answered (in the spec, an ADR or this session) is not asked again.

## Prompt format

The page produces one line per decision: `D3 <title>: <option name> [<option id>] (recommended)` or `(not the recommendation)`, with `Note:` for the user's text and `NOT SURE. Question:` when unsure. Do not change this format; step 7 parses it by eye and the check script asserts it.
