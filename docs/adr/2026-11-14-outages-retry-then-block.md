---
scope: repo
repo: factory
topic: outages-retry-then-block
status: accepted
supersedes: []
---

# Outages

## Decision

After three tries the run is `retrying`; each tick retries for `infra_wait_hours` (6) before blocking

## Source

Backfilled on 2026-11-16 from `docs/reviews/phase-1-decisions.md`, decision `D13`. The owner chose this on 2026-11-14; the answer is the record's, not new.
