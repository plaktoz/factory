---
scope: repo
repo: factory
topic: rebuild-run-from-last-snapshot
status: accepted
supersedes: []
---

# How a run is rebuilt from its events

## Decision

a `run_snapshot` event after each change, carrying the whole run; a rebuild replays only the last one

Chosen option: `snapshot-event`.

## Context

`run.json` is written atomically, so a crash never leaves half a file; tested, the old or the new file is always whole. It is unreadable only after disk damage or a hand edit. `Run` has 18 fields and a rebuild must restore 16 of them (heartbeat and signals are recomputed). The catalogue's 38 events carry no fields today.

## Options considered

- **`snapshot-event`** (chosen) (recommended): Add one event, `run_snapshot`, written after each change and carrying the whole run; rebuild replays the last one
  - For: One new event and one rule; rebuild is a few lines and cannot miss a field when `Run` gains one
  - For: Measured: a mid-run snapshot is 1.8 KB, so 200 changes add about 356 KiB to `events.jsonl`
  - For: Needs no change to the other 38 events or to the modules that write them
  - For: The test already states the requirement; when the fix lands the strict marker makes the suite fail until the marker is removed (checked with pytest), so the gap cannot be closed silently
  - Against: Events.jsonl grows faster; the dashboard and `read_events` readers must skip or ignore snapshots
  - Against: The history is a series of full states, not a story of what changed; a reader wanting 'what changed' must diff two snapshots
  - Against: A snapshot can hold a value that was wrong when written, so a rebuild reproduces the wrong value
- **`fields-on-events`**: Make every catalogue event carry the fields it changes, and rebuild by replaying them
  - For: No extra event and a smaller log: only the changed fields are written
  - For: The log reads as a story, which suits the dashboard's run history and audits
  - Against: A large spec edit: about 38 events each need a field list, across modules 6, 8, 9, 11, 12, 13 and 14
  - Against: Every future change to `Run` or to a module's state must also change an event, or the rebuild silently drifts
  - Against: Rebuild is replay logic that must be correct for 16 fields in every order of events, and is easy to get subtly wrong
- **`backup-copy`**: Keep the previous `run.json` as `run.json.bak` on each write; `recover --rebuild` restores it and closes open attempts
  - For: Smallest change: one copy per write, no new event, no change to the catalogue
  - For: Covers the case that can actually happen, a damaged or hand-edited `run.json`, because atomic writes already stop crashes from corrupting it
  - Against: The backup is one write behind, so a rebuild can lose the last change and must be reconciled with the events
  - Against: Does not satisfy module 6A's wording: 'from events', 'the same status, stages, loops and attention'
  - Against: If both files are damaged, nothing can be rebuilt

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

One snapshot event is the smallest change that meets 6A as written, and its cost is measured at under 400 KiB for a long run.

## Source

Backfilled on 2026-11-16 from `docs/reviews/../tasks.md (Log, 2026-11-15 wave 1, module 6A)`, decision `E1`, page `docs/reviews/rebuild-run-decisions.json`. The owner chose this on 2026-11-15; the answer is the record's, not new.
