# PR #43 Codex adapter: notes

Page: `docs/reviews/pr43-codex-decisions.html`. Data: `docs/reviews/pr43-codex-decisions.json`. PR #43 stays on its own page and is not repeated on [the wave 3 open decisions page](wave3-open-decisions.md).

## Answers

**No answers are recorded.** The task that produced this note said PR #43 should "follow the answers on its own page", but the pasted reply covered only D1 and D2 of the wave 3 page. Neither the repo, the PR (no comments, no reviews) nor the session notes hold a choice for D1 (sandbox promise) or D2 (what happens to the PR). Nothing was applied, and D7 was not changed. The recommendations on the page are `accept-both-codex-only` for D1 and `hold-resolve-conflict` for D2; they are recommendations, not decisions.

PR #43 stays open and unmerged until the owner answers that page.

## Module 09 conflict (checked 2026-11-15, `origin/main` at `b04add6`)

`git merge-tree origin/main origin/plaktoz/feat-p2-1-codex` reports one conflict, in `docs/design/modules/09-worker-adapters-and-governed-helpers.md`, in two acceptance criteria. `docs/design/phase-2.md` and `test_claude_adapter.py` merge cleanly.

| Criterion | `main` | PR #43 | Which is right |
| --- | --- | --- | --- |
| The `doctor` probe worker loads none of your personal instructions, plugins, hooks or MCP servers | Unticked. Plugins, MCP servers and hooks are asserted; personal instructions are not, because the init event does not list them | Ticked, citing only the plugin and MCP tests | **`main`.** Neither branch has a test for personal instructions (`grep -i personal` on both: only the plugin and MCP test). The tick overstates what is proven. |
| `CommandAdapter` runs a command, a script and a plugin function and kills each at its timeout | Unticked: the kill tests need `srt` and skip | Ticked, with seven tests, including the child's PID being gone after the timeout | **PR #43**, which the 24 `test_command_adapter.py` tests passing without skips on this machine support (`srt` 0.0.83, 2026-11-15). Linux is untested. |

Resolution for whoever rebases the PR (not done here, because the PR branch belongs to its author): keep `main`'s unticked text for the first criterion, and take the PR's ticked text and test list for the second. Rerun both suites, one at a time, after the rebase.

## Open items from the PR, unchanged

Criterion 20 (same gate evidence on both harnesses) is unproven. The module 9 doctor canary, the gate-command `srt` check and the cache tests are not done. The `api.openai.com` default is untested. There is no MCP isolation test for Codex. `srt` is pinned at 0.0.83 and tested on macOS only. The smoke results are the author's and are not reproduced here.
