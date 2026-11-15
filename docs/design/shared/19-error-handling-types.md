# 19. Error handling types

Part of the [phase 1 design](../phase-1.md#shared-sections).

Every error falls into one of five handling types, and each module maps its failures onto them. A run never fails silently: each error writes an event, and anything a person must act on becomes an attention item.

| Type | Handling | Example |
| --- | --- | --- |
| Fail fast | Stop before any work, name the file, line and fix; exit 2 | A missing `${ANTHROPIC_API_KEY}` |
| Transient retry | Three tries with waits of 5 s and 30 s, then wait and retry on each tick for `infra_wait_hours`, then block | GitHub rate limit |
| Task retry | New attempt from the last checkpoint, up to `retries` | Worker crash |
| Rework | Route to an earlier stage with a feedback record | Tests fail |
| Human | Raise an attention item and wait | Loop maximum reached |

Each module's own failures, and which type handles each, are listed in its **Module contract** under Errors. A module raises `FactoryError` with the matching `kind`, and 8's `classify` turns it into the handling type.
