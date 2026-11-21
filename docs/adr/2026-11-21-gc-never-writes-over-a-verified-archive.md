---
scope: repo
repo: factory
topic: gc-never-writes-over-a-verified-archive
status: accepted
supersedes: []
---

# gc never writes a new archive over a zip that verifies

## Decision

Accepted by the owner on 2026-11-21, in the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them: fix the archive-overwrite bug in the code.

Before archiving a run, `gc` looks for a zip of that run that passes `testzip()` and holds the run's `run.json`, at the planned path or in any month's folder. If one exists and the run folder matches it, `gc` records history and removes the folder. If the folder does not match, `gc` reports a failure and keeps both.

## Context

`_write_archive` moved a new temporary zip onto the planned path with `os.replace`. After a crash during the deletion of an archived run's folder, the folder was still there, so the next `gc` archived it again and replaced a complete zip with one built from a half-deleted folder. The code is `_verified_archive` and `_differs_from_zip` in `housekeeping.py`.

## Options considered

- **Fix the code (chosen).** Verify an existing zip first, and never write over it.
  - The walkthrough's option list is not in the repo, so no alternatives are listed. This record states the answer the owner gave.

## Why

Once a run's folder is deleted, its zip is the only copy, so a complete zip must not be replaced by a partial one.

## Consequences

- Tests: `test_a_second_gc_after_a_crash_in_the_deletion_keeps_the_complete_zip`, `test_a_leftover_folder_the_zip_does_not_match_is_kept_and_reported`, `test_an_archive_zip_that_does_not_verify_is_written_again_from_the_folder`.
- A zip that does not verify is written again from the folder, as before.
- Commit `6a69067`, PR #73.

## Source

Written on 2026-11-21 by Claude Code from the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them. The answer is the owner's, not new.
