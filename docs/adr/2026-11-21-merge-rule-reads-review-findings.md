---
scope: repo
repo: factory
topic: merge-rule-reads-review-findings
status: accepted
supersedes: []
---

# The merge rule reads review findings, and blocks on medium or high

## Decision

Accepted by the owner on 2026-11-21, on the question "C9": the merge rule `never_auto_if.review_findings_at_or_above` fails for any run with a review stage, but the review-findings schema exists and the gate reads it. The owner chose "Read findings in the merge rule". What now holds:

- The rule reads each review stage's findings with `factory/schemas/review-findings.schema.json`.
- A finding at or above the policy's threshold (`medium` in the shipped policy) blocks auto-merge.
- A review task with no findings file, or a file that fails the schema, also blocks auto-merge, because the decision cannot be made on findings nobody could read.
- The run summary reports the same findings and their count, so the summary and the merge decision read one source.

## Context

The rule's text said "review findings cannot be read yet (no review-findings schema)", and it blocked every run with a review stage. That was true before the schema was accepted (`2026-11-15-accept-draft-report-schemas`) and is no longer true. The spec's threshold is in `docs/design/modules/13-delivery.md`, `review_findings_at_or_above: medium`.

Checked on 2026-11-21:

- `factory/schemas/review-findings.schema.json` exists, and `factory/engine/factory_engine/gates.py` (`check_findings`) reads it for the `no-blocking-findings` gate.
- The shipped `chore` workflow has no review stage, so the rule has never changed a shipped auto-merge decision. `bug-fix` has a review stage and never auto-merges in phase 1a.
- The full engine suite passed on the change: 987 passed, 2 skipped, 0 failed, 27 min 35 s (run before this ADR was committed, on the same code).

## Options considered

- **`read-findings`** (chosen): read the findings and block on medium or high.
  - For: the rule matches the spec's threshold and the schema that already exists.
  - For: a run whose findings cannot be read still waits for a person.
  - Against: a bad findings file now blocks a run that the old rule would also have blocked, so no run becomes less safe.
  - Against: a finding is only as good as the reviewer task that wrote it. The schema is still a draft with no live run (see `2026-11-15-accept-draft-report-schemas`).
- **`keep-blanket-block`** (not chosen): keep blocking every review stage, and fix only the wording.
  - For: no change to merge behavior.
  - Against: the rule says a check is impossible when it is possible, and it can never allow a review-stage run to auto-merge, so the rule is stricter than the owner's own spec.
- **`record-only`** (not chosen): leave the code and the text, and add a task.
  - For: no change at all.
  - Against: the stale text stays in two places the user reads.

## Why

The spec gives a threshold and the schema is accepted. Reading findings is what the spec describes, and the blanket block contradicts both.

## Consequences

- **Changes now:** `factory/engine/factory_engine/delivery.py` (the rule), `summary.py` (the reader and the summary line), and `tests/delivery/test_delivery.py`.
- **Not changed:** `chore` is still the only auto-merge workflow, and its policy is unchanged.
- **Still true:** the schema has had no live run, so a real reviewer's output may need a field change. That risk is recorded in `docs/tasks.md` item 4.
- **Task:** `docs/tasks.md` item 35.

## Source

Written 2026-11-21 by the Claude Code session that applied the owner's answer to the open item "C9" (session `bee82625-ef4d-4d09-bb43-45c945a7fbab`).
