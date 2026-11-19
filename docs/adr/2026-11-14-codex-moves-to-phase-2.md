---
scope: repo
repo: factory
topic: codex-moves-to-phase-2
status: accepted
supersedes: []
---

# Codex moves to phase 2

## Decision

The Codex worker adapter (P2-1) is out of phase 1. It is tracked in `docs/design/phase-2.md`. Phase 1 keeps what the adapter needs later: the worker adapter contract, the `harness` and `routing` config keys, and the `harnesses` map. Adding Codex then changes no workflow.

There was no option list for this: it was a statement, not a decision page.

## Context

On 2026-11-14 the owner said phase 2 is not needed now and phase 1 comes first. Phase 1 supports Claude only. The Codex adapter was built on PR #43, which was merged on 2026-11-16 under [the hold ADR](2026-11-15-hold-pr-43-until-the-d7-record-is-on-main.md).

## Source

The owner's statement is in `docs/tasks.md`, Log, 2026-11-14 ("Owner said phase 2 is not needed now; phase 1 first"). The move was recorded as a section of `746ec67:docs/reviews/phase-1-decisions.md`, "Moved to phase 2 (2026-11-14)".
