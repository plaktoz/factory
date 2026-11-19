---
scope: repo
repo: factory
topic: hold-pr-43-until-the-d7-record-is-on-main
status: accepted
supersedes: []
---

# Hold PR #43 until its D7 record is on main

## Decision

PR #43 (the Codex worker adapter, P2-1) stays open until its author resolves the conflict in module 9. It merges only after the D7 residual-risk record for Codex workers is on `main`, as [the Codex residual-risk ADR](2026-11-15-codex-sandbox-residual-risk-accepted.md) states. The decision and the merge stay in that order.

Chosen option: `hold-resolve-conflict`.

## Context

On 2026-11-15 PR #43 was open, not merged, and conflicting with `main` in module 9. Its open items then: criterion 20 (same gate evidence on both harnesses), the doctor canary, the gate-command `srt` check, the cache tests, the `api.openai.com` default, MCP isolation for Codex, and Linux. Phase 1 does not build phase 2 items.

## Options considered

- **`hold-resolve-conflict`** (chosen, recommended): the decision and the merge stay in order. Cost: the adapter stays unmerged for now, and it needs a rebase and a rerun of both suites.
- **`merge-after-rebase`**: rebase, rerun both suites and merge now, opening the missing items as tasks. Cost: a weaker isolation level reaches `main` before D7 records it, and criterion 20 and the canary are unproven at merge.
- **`split-deny-read-fix`**: merge only the `~/.codex` deny-read fix now. Cost: the adapter waits for D1, and the fix lives in shared sandbox code, so the author must split it.

## Status

The PR was merged on 2026-11-16 as `683e3e5`. `docs/tasks.md` item 10 records the merge and what was checked after it.

## Source

Answered on 2026-11-15 on page `746ec67:docs/reviews/pr43-codex-decisions.json` (the folder was deleted after that commit), decision `D2`, option `hold-resolve-conflict`, which was the recommended option. The owner's answer is the record's, not new.
