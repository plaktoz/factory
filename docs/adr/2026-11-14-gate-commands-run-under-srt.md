---
scope: repo
repo: factory
topic: gate-commands-run-under-srt
status: accepted
supersedes: []
---

# Sandbox for gate commands and cmd tasks

## Decision

run every `cmd` task and gate command under `srt` with the workers' read and write rules

Chosen option: `srt-wrap`.

## Context

D7 turns on Claude Code's sandbox, which covers only Claude workers. A gate such as `make build` and any `cmd` task runs through CommandAdapter as a plain subprocess, with the engine's full access to your files. Tested on macOS: Anthropic's standalone `srt` (@anthropic-ai/sandbox-runtime 0.0.83) denied a read, refused a write outside the worktree, allowed one inside it, and ran a piped command.

## Options considered

- **`srt-wrap`** (chosen) (recommended): Run every cmd task and gate command under srt, with the same read and write rules as the workers
  - For: Same boundary for workers and commands, built by Anthropic
  - For: Tested: read denied, outside write refused, in-worktree write allowed
  - For: The repo's own scripts cannot read the factory home
  - Against: One more dependency: an npm package, pinned at 0.0.83, that the kit must install and doctor must check
  - Against: Linux is not tested, and the macOS path rests on the deprecated sandbox-exec
  - Against: Build tools that write caches outside the worktree fail until listed (see Q2)
- **`leave-open`**: Leave cmd tasks and gates unsandboxed and state it as residual risk
  - For: No new dependency or code
  - For: No cache-path problems for builds
  - Against: A gate command runs with full user access, so D7 protects workers but not the repo's own scripts
  - Against: A planted script in the repo can read the factory home
- **`own-wrapper`**: Write the factory's own sandbox-exec and bubblewrap wrapper for commands
  - For: The factory owns the profile
  - Against: Two code paths to build and test
  - Against: Duplicates what srt already does
  - Against: This was the option D7 declined

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

srt is the same mechanism Claude uses, it passed the same canary, and it closes the one path D7 left open.

## Source

Backfilled on 2026-11-16 from `docs/reviews/open-decisions.md`, decision `Q1`, page `docs/reviews/open-items.json`. The owner chose this on 2026-11-14; the answer is the record's, not new.
