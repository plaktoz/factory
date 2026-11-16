---
scope: repo
repo: factory
topic: claude-sandbox-for-workers
status: accepted
supersedes: []
---

# Worker isolation: how to stop a worker reading secrets

## Decision

Claude Code's own sandbox setting on for every worker, reads of secrets denied, writes only to the worktree and `$FACTORY_TASK_DIR`, `doctor` runs the canary each time

Chosen option: `claude-sandbox`.

## Context

D7 accepted a tool allowlist, a scrubbed environment and denied reads, with no OS sandbox (the spec says so in module 9 and the phase split). A canary test showed a Read deny rule blocks only the Read tool, and an allowed `python3` read the file anyway. Tested on macOS with Claude Code 2.1.325: its own sandbox setting (`sandbox.filesystem.denyRead`, `allowWrite`) blocked that read, and writes worked only in the worktree and the task folder. That setting runs each Bash command under `sandbox-exec` (seen in the process list), which the man page marks DEPRECATED; the binary also names `bwrap` for Linux. Not tested: Linux, and an OAuth login.

## Options considered

- **`claude-sandbox`** (chosen) (recommended): Turn on Claude Code's own sandbox setting for every worker, with denied reads for secrets and writes only to the worktree and `$FACTORY_TASK_DIR`; `doctor` runs the canary each time
  - For: Tested: it blocks the interpreter read that beat the deny rule
  - For: Tested: writes to the worktree and task folder work; other paths are blocked
  - For: Anthropic keeps the sandbox profile, and the engine adds no wrapper code
  - Against: Claude only; a second harness in phase 2 needs its own boundary
  - Against: On macOS it rests on `sandbox-exec`, which is marked DEPRECATED, so a future macOS can break it; `doctor` must prove it on each machine
  - Against: The setting names can change between releases; Linux is not tested here
- **`own-sandbox`**: The factory wraps each worker itself: `sandbox-exec` on macOS and `bubblewrap` on Linux
  - For: Same boundary for any harness, including Codex later
  - For: Tested on macOS: blocks both `python3` and `cat` reads of a denied file
  - For: The factory owns the profile, so a harness update cannot loosen it
  - Against: Same deprecated `sandbox-exec` on macOS, and the factory must maintain the profile
  - Against: Two code paths to build and test, and `bubblewrap` is not tested here
  - Against: More engine code in phase 1a
- **`keep-d7`**: Keep D7 as accepted: allowlist and scrubbed environment only, with the open interpreter route reported by `doctor`
  - For: No new code
  - For: Residual risk is already stated in module 9
  - Against: Tested: an allowed interpreter reads a denied file
  - Against: A task allowed an interpreter can read your other secrets

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

It is the only option tested to close the gap without engine code, and both sandbox options rest on the same macOS mechanism, so the choice is who maintains it.

## Source

Backfilled on 2026-11-16 from `docs/reviews/open-decisions.md`, decision `D7`, page `docs/reviews/open-decisions.json`. The owner chose this on 2026-11-14; the answer is the record's, not new.
