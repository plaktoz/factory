---
scope: repo
repo: factory
topic: build-caches-in-task-dir
status: accepted
supersedes: []
---

# Where build caches go under the write boundary

## Decision

the adapter points each tool's cache into the task's `work/` folder

Chosen option: `cache-in-task-dir`.

## Context

Tested with the sandbox on: a write to ~/.npm failed with Operation not permitted, while a write inside the worktree worked. npm, Maven and Gradle write caches under your home folder, so a worker or gate that installs or builds fails unless the cache path is writable. Tested names: npm_config_cache works and npm_cache does nothing.

## Options considered

- **`cache-in-task-dir`** (chosen) (recommended): Point each tool's cache at a folder under the task's work/ folder (npm_config_cache, MAVEN_OPTS, GRADLE_USER_HOME), set by the adapter
  - For: The write boundary stays exactly two paths
  - For: Nothing a worker writes persists outside the run
  - For: No shared cache for one run to poison
  - Against: Each task downloads dependencies again, so builds are slower
  - Against: Each language profile in 17A needs its cache variable named
  - Against: Needs network access to the package registry for every task
- **`shared-cache-dir`**: Add one factory cache folder, such as $FACTORY_HOME/cache, to allowWrite and point every tool at it
  - For: Dependencies download once per machine
  - For: Faster builds
  - Against: A third writable path, shared across runs and repos
  - Against: One run can write a bad package that a later run installs
  - Against: Breaks the 'writes only to the worktree and task folder' rule that D7 states
- **`allow-home-caches`**: Add ~/.npm, ~/.m2 and ~/.gradle to allowWrite
  - For: Tools work unchanged
  - Against: A worker can write into your own tool caches
  - Against: Breaks the D7 rule
  - Against: Cache poisoning reaches your own builds

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

It keeps D7's two-path rule intact, and speed can be bought back later with a read-only shared cache.

## Source

Backfilled on 2026-11-16 from `docs/reviews/open-decisions.md`, decision `Q2`, page `docs/reviews/open-items.json`. The owner chose this on 2026-11-14; the answer is the record's, not new.
