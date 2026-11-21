---
scope: repo
repo: factory
topic: run-the-engine-suite-with-pytest-xdist
status: accepted
supersedes: []
---

# Run the engine suite with pytest-xdist

## Decision

Accepted on 2026-11-21, by the owner's instruction in the session: "start item 24", then "start the pytest-xdist commit". Task item 24 in `docs/tasks.md` set the order: measure first, then add the dependency in its own commit.

`pytest-xdist` 3.8.0 is added to the engine's dev dependency group in `factory/engine/pyproject.toml`, alongside `pytest>=8`. The engine suite can then run in parallel with `pytest -n <workers>`. The default run stays serial, so nothing changes for a run that does not ask for workers.

## Context

What was measured on 2026-11-21, on a 10-core machine (commands and numbers are in `docs/tasks.md`, item 24):

- The serial suite takes 388.6 s with a clean `HOME` (945 passed, 2 skipped).
- On the merged tree at `b5c45a8`, `-n 8` takes 148.5 s and passes 980 tests, 2 skipped, with no failure.
- Two parallel failures were found and fixed before the timings above were trusted. One was a one-shot process check that read a killed process too early (`tests/workers/process_gone.py`). The other was a browser test that waited on the owner's running Chrome, now given its own profile.

Facts about the package, checked on 2026-11-21:

- Version 3.8.0 was uploaded on 2025-07-01, so it is more than two weeks old.
- It requires `execnet` and `pytest`. Nothing else.
- `uv.lock` is ignored by git (`.gitignore`), so no lock file is committed; the version is pinned by the `pyproject.toml` range only.

## Options considered

- **`pytest-xdist` in the dev group, `>=3.8,<4`** (chosen): the dependency is declared where the other test dependency (`pytest>=8`) already is.
  - For: installing the dev group gives the same test setup for everyone.
  - For: serial runs are unchanged.
  - Against: a new dependency for every developer and any copy that installs the dev group.
- **Install it by hand in each environment, not in `pyproject.toml`**: no dependency change.
  - For: nothing new in the project.
  - Against: every person and every CI job has to know to install it, and a missing install shows up only as an unknown `-n` option.
- **Use `pytest-xdist` only in a separate optional group**: keeps the core dev group unchanged.
  - For: a clear split.
  - Against: the normal test command would still need a second install step, which is the same problem as the second option.

## Why

The measured timings show a large gain, and the two parallel failures that blocked trust were fixed first. A dev-group dependency is the one place where everyone who runs the tests gets the same setup.

## Consequences

- `factory/engine/pyproject.toml`: the dev group gains `pytest-xdist>=3.8,<4`.
- Commands that run the suite can add `-n <workers>`. The spec's "Run and test" lines are unchanged, and they still work serially.
- Not decided here: the default worker count, and whether CI runs parallel. Neither is set by this ADR.
- Not decided here: the company `pre-push` and `pre-commit` secrets scans, which still run on every commit and push in the tests. That is the owner's call with security (task item 24).
- Task: item 24 in `docs/tasks.md`, to be checked off in the same commit that adds the dependency.

## Source

Written on 2026-11-21 by the session that ran the timings, from the owner's instruction to start item 24 and then the pytest-xdist commit. The timing numbers come from runs in this session, recorded in `docs/tasks.md`.
