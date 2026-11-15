# PR #43 Codex adapter: notes

Page: `docs/reviews/pr43-codex-decisions.html`. Data: `docs/reviews/pr43-codex-decisions.json`. PR #43 stays on its own page and is not repeated on [the wave 3 open decisions page](wave3-open-decisions.md).

## Answers (applied 2026-11-15)

| Decision | Choice | Recommended? | Applied in |
| --- | --- | --- | --- |
| D1 Sandbox promise for Codex workers under D7 | `accept-both-codex-only` | Yes | [Module 9](../design/modules/09-worker-adapters-and-governed-helpers.md), "Threat model and isolation": a Codex-only residual risk item under Residual risk, and a pointer from that bullet; [phase-1-decisions.md](phase-1-decisions.md), "D7 residual risk for Codex workers" |
| D2 What happens to PR #43 now | `hold-resolve-conflict` | Yes | PR #43 stays open, with a comment saying its author resolves the module 9 conflict and that the merge waits for the D7 record |

The earlier version of this file said no answers were recorded. That was true when it was written; the answers arrived afterwards and are above.

Two things were not changed, on purpose. `docs/design/phase-2.md` still says "Workspace-write sandbox" in its Claude and Codex comparison table and has the "To confirm" ticks, because PR #43 edits the same lines and a second edit here would add a conflict; the PR's author updates them while resolving the conflict. PR #43's own module 9 text for the Codex adapter ("One sandbox layer", "Settings") already states both changes; once rebased it should link to the D7 record and not restate the risk.

## Module 09 conflict (checked 2026-11-15, `origin/main` at `b04add6`)

`git merge-tree origin/main origin/plaktoz/feat-p2-1-codex` reports one conflict, in `docs/design/modules/09-worker-adapters-and-governed-helpers.md`, in two acceptance criteria. `docs/design/phase-2.md` and `test_claude_adapter.py` merge cleanly.

| Criterion | `main` | PR #43 | Which is right |
| --- | --- | --- | --- |
| The `doctor` probe worker loads none of your personal instructions, plugins, hooks or MCP servers | Unticked. Plugins, MCP servers and hooks are asserted; personal instructions are not, because the init event does not list them | Ticked, citing only the plugin and MCP tests | **`main`.** Neither branch has a test for personal instructions (`grep -i personal` on both: only the plugin and MCP test). The tick overstates what is proven. |
| `CommandAdapter` runs a command, a script and a plugin function and kills each at its timeout | Unticked: the kill tests need `srt` and skip | Ticked, with seven tests, including the child's PID being gone after the timeout | **PR #43**, which the 24 `test_command_adapter.py` tests passing without skips on this machine support (`srt` 0.0.83, 2026-11-15). Linux is untested. |

Resolution for whoever rebases the PR (not done here, because the PR branch belongs to its author): keep `main`'s unticked text for the first criterion, and take the PR's ticked text and test list for the second. Rerun both suites, one at a time, after the rebase.

## Open items from the PR, unchanged

Criterion 20 (same gate evidence on both harnesses) is unproven. The module 9 doctor canary, the gate-command `srt` check and the cache tests are not done. The `api.openai.com` default is untested. There is no MCP isolation test for Codex. `srt` is pinned at 0.0.83 and tested on macOS only. The smoke results are the author's and are not reproduced here.
