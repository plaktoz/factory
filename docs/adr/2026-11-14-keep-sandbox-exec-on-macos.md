---
scope: repo
repo: factory
topic: keep-sandbox-exec-on-macos
status: accepted
supersedes: []
---

# Keep macOS sandbox-exec under the worker sandbox

## Decision

Keep `sandbox-exec`, the macOS mechanism that Claude Code's sandbox and `srt` both use. It is not dropped. If a future macOS breaks it, `doctor` fails closed, and the fix is a new decision.

Chosen: keep (the owner's condition for dropping it was not met).

## Context

The man page of `sandbox-exec` marks it DEPRECATED. The owner set the condition for dropping it: drop it only if no alternative exists and it is not a project requirement. Both parts were checked on 2026-11-14:

- An alternative exists in principle, not in practice. None was tested with the same boundary: Docker, Colima, Lima and OrbStack are not installed. Podman runs a Linux VM, which would change the platform model of D6, and it was not tested.
- The boundary is a project requirement. D7 requires reads of secrets to be denied and writes to be limited to the worktree and the task folder. Dropping `sandbox-exec` drops that boundary.

`srt` 0.0.83 and the Claude Code 2.1.325 binary both use it. The owner can supersede this with a new ADR.

## Source

The owner's condition is in `docs/tasks.md`, pending request item 2 ("drop `sandbox-exec` only if no alternative exists and it is not a project requirement"). The check is in `746ec67:docs/reviews/open-decisions.md`, "Round 3: pending items 2 and 3". The verdict applies the owner's condition; the owner did not pick it from an option list. Recorded as done, kept, in `docs/tasks.md`.
