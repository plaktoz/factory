---
scope: repo
repo: factory
topic: node-26-is-the-factory-node
status: accepted
supersedes: []
---

# The factory runs on Node 26

## Decision

The factory's Node version is 26, tested on Node 26.13.0 (LTS "Lithium"). The floor for `srt` stays at Node 22.12, its `engines` field. Node 25 is not used.

Chosen option: Node 26.

## Context

`srt` 0.0.83 ran on Node 26.13.0 with a settings file that validates. The file needs `network.deniedDomains` and `filesystem.denyWrite`, which the `srt` README example omits; without them `srt` refuses to run. Node 26 issues beyond those tests are not assessed. Module 9 names Node 26 as the tested version.

## Source

The owner chose Node 26 over Node 25 on 2026-11-14 (`docs/tasks.md`, pending request item 3, "owner's choice"). The tests are in `746ec67:docs/reviews/open-decisions.md`, "Round 3: pending items 2 and 3".
