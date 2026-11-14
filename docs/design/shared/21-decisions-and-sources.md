# 21. Phase 1 decisions and sources

Part of the [phase 1 design](../phase-1.md#shared-sections).

All seven open questions are decided, and the modules they affect have been updated. Three interactions between choices need a rule; they are listed under the table.

| # | Question | Decision | Modules updated |
| --- | --- | --- | --- |
| 1 | Several markdown files at once | One run for all files in one submission | 4 Intake |
| 2 | Branches for read-only workflows | Detached worktree while working; a branch only at delivery, when the doc sink writes into the repo | 2 Glossary, 5 Workflows, 7 Git, 13 Delivery |
| 3 | Merge policy at the start | Small chores auto-merge when every rule passes; everything else needs human review | 13 Delivery |
| 4 | Run id separator | Hyphen everywhere: `new-color-q1w2e` for branch, worktree and run folder | 3 Kit |
| 5 | Answering by GitHub comment | Phase 2 | 11 Human stops |
| 6 | Chat webhook | Optional, off by default (`notify.webhook: null`) | 3 Kit, 11 Human stops |
| 7 | Takeover for live steering | After phase 1 | 12 Live view |

**Interactions between choices**

- **Auto-merge for chores (3) and triage ([module 4](../modules/04-intake-and-triage.md)).** If the LLM fallback guesses "chore", a mislabeled request could auto-merge. Rule: auto-merge needs the type to come from an explicit type, label or front matter, never the LLM fallback (`require.type_source: [explicit, label, front_matter]`).
- **One run per submission (1) and chore limits (3).** Bundling several files makes a run larger. The `max_files` and `max_lines` limits still apply, so a bundled chore over the limits falls back to human review instead of auto-merging.
- **Phone access with webhook (6) and comment answers in phase 2 (5).** Webhook and GitHub messages link to the local dashboard and file paths, which only open on the machine running the factory. In phase 1, you can be told on your phone but must answer at that machine. Comment commands in phase 2 close this gap.

The read-only choice (2) also resolves an earlier contradiction: the doc sink can deliver a report through a pull request, which needs a branch.

**Sources**

The Codex sources moved to `docs/design/phase-2.md` with the Codex adapter.
