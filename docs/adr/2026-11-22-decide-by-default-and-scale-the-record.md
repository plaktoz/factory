---
scope: repo
repo: factory
topic: decide-by-default-and-scale-the-record
status: accepted
supersedes:
  - 2026-11-14-decide-at-the-recommendation
---

# Sessions decide by default, and a decision's record matches its cost

## Decision

Accepted by the owner on 2026-11-22, in the session, with the words "go ad approve all changes. do it in one branch", after a diagnosis of why the owner spent more time deciding than the agents spent building.

What now holds:

1. **Decide by default.** A session takes the recommended option and keeps working. It stops for the owner only on a **stop trigger**: the choice reopens D1 to D14 or an accepted ADR; it changes scope or phase; it costs a lot to reverse (a public post under the owner's name, a data format or shared contract other work reads, a new dependency); or no option is clearly better. The rule lives in `AGENTS.md`, under Working rules, so every agent reads it.
2. **The record matches the cost.**

   | Choice | Record |
   | --- | --- |
   | A bug fix, a test, or record upkeep (a re-run, a renumber, a corrected count) | The commit message. No ADR, no task, no page. |
   | A reversible choice made at the recommendation | One line in `docs/decisions.md`. The owner skims it and says "undo `<slug>`" to reverse one. |
   | A stop trigger | An ADR, and a card on the next decision page. |

3. **One decision page a day at most.** Stop triggers queue as `proposed` ADRs. The session keeps working on whatever they do not block.
4. **Every card names its trigger.** The decision-page renderer refuses a card without a `trigger` from the four above, so a question with no stop trigger cannot reach the owner.
5. **Routine outward steps are approved once.** A session may push its own branch, open a pull request for it, and merge `origin/main` into it just before the push. This is a row in `docs/approvals.md`. It replaces the `AGENTS.md` rule "Do not run `git pull`, `git fetch` or `git merge`", which contradicted the 2026-11-14 approval that a checkpoint is a commit, push and merge without asking.
6. **Product before process.** Until item 12 in `docs/tasks.md` (a full live run of a factory run) is done, sessions build product code. A new skill, check script, calibration round or process ADR needs the owner to ask for it.
7. **`docs/tasks.md` holds only live state.** Closed items, finished sections and all but the newest Log entries move to `docs/tasks-archive.md`. `records.py` caps the Log in `docs/tasks.md`.

## Context

Measured on 2026-11-22 by running `git` and `grep` over the repo, for 2026-11-14 to 2026-11-22:

- 94 ADRs were written, 37 of them on 2026-11-21. 81 say "Accepted by the owner". One says "decided at recommendation", the record `2026-11-14-decide-at-the-recommendation` asked for.
- The owner chose the recommended option in at least 34 ADRs that say so, and chose another option in 2 (`2026-11-21-correct-the-strong-adr-spread-to-five-runs`, `2026-11-21-propose-pilot-tickets-from-issues`).
- Of the 198 non-merge commits from 2026-11-14 to 2026-11-22, 77 touched `factory/` (39%), 117 touched only `docs/`, and 4 touched other paths (`git diff-tree` per commit; `scripts/code-share.py 9` gives the same 77 of 198).
- `docs/tasks.md` was 16,952 words and the ADRs 38,221. Every session reads the first and reconciles both.

The 2026-11-14 rule did not hold, for four reasons:

- It lived in an ADR and in step 1 of the `decision-page` skill, not in `AGENTS.md`. `AGENTS.md` said the opposite in broader words: "An architecture choice stops your work" and "Before you build on a choice other work will depend on, write an ADR". A session that could not tell which rule won asked the owner.
- Every decision got a full ADR with checked context, options, consequences and a source, then a task and a Log entry, which `records.py` check 5 enforces. A record that costly reads as something that needs a signature.
- Many questions were not decisions: bug fixes (`2026-11-21-gc-keeps-a-branch-that-has-unpushed-commits`, `2026-11-21-usage-reads-the-last-whole-line-for-each-attempt`), routine pushes (`2026-11-21-push-the-branch-and-open-a-pull-request`, `2026-11-22-merge-main-before-the-push`), and record upkeep (`2026-11-21-correct-the-strong-adr-spread-to-five-runs`, `2026-11-21-rescore-the-three-design-files-now`).
- Process work made more process work. Most of the 67 commits of 2026-11-21 built, calibrated and re-measured the `revise-spec` skill. Item 12, a full live run, stayed open.

## Options considered

- **Decide by default, with a record that matches the cost, and enforce the trigger in the renderer** (chosen, recommended).
  - For: the owner sees only questions that meet a trigger, about one page a day. A wrong reversible choice costs one "undo" line. The renderer makes the rule hard to skip, where text alone failed once.
  - Against: the owner learns of reversible choices after the fact and must skim `docs/decisions.md` to veto. A session may mislabel a costly choice as reversible. The trigger list is the guard, and the owner can tighten it.
- **Keep the 2026-11-14 rule and restate it more strongly** (not chosen).
  - For: no new files, no change to `records.py` or the renderer.
  - Against: it is the rule that held for 1 decision in 81. Text that loses to a broader rule in `AGENTS.md` loses again.
- **Owner decides everything, but batched** (not chosen).
  - For: the owner keeps full control.
  - Against: it keeps the cost that started this. With about 95% of answers at the recommendation, a question per choice buys little.

## Why

The owner agreed with the recommendation about 95% of the time, so asking costs more than an occasional undo. The rule failed because of where it lived and how much a record cost, not because of what it said. So this decision moves the rule into the file every agent reads, makes the cheap path cheap, and puts the trigger into the renderer so the page itself enforces it.

## Consequences

- `AGENTS.md`: Working rules carry decide-by-default, the record tiers, the stop triggers, the merge-main rule and the product-first pause. The Ask-first row points at the stop triggers.
- `docs/decisions.md` is new: one line per reversible choice.
- `docs/approvals.md` gains the push, pull request and merge-main row.
- `.claude/skills/decision-page/`: step 1 points at `AGENTS.md`. The schema gains `trigger` and `trigger_detail`. `render.py` refuses a card without them, and the page shows "Asked because" on each card. `test_render.py` checks this.
- `docs/tasks.md` is cut to live state. `docs/tasks-archive.md` holds the rest. `records.py` check 5 accepts an ADR named in either file, check 7 caps the Log in `docs/tasks.md` at 12 entries, and check 8 checks the line format of `docs/decisions.md`.
- `scripts/code-share.py` is new. It reports the share of commits that touch `factory/` and the ADRs written per day. Target: more than 60% of commits touch `factory/`.
- Not changed: the pilot rules in `AGENTS.md` under "Specs and checks" (spec approval before code, the fresh-session check). They rest on their own 2026-11-21 ADRs. The pilot's end decides them.
- The pause in point 6 ends when item 12 is `[x]`. No new ADR is needed to end it.

## Source

Written on 2026-11-22 by the session that ran the diagnosis (Claude Code, run `45f6ee60-29af-485c-a3aa-73e0dd328a80`), on branch `plaktoz/decide-by-default`. The owner's approval is quoted under Decision. No decision page was used.
