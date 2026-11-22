---
scope: repo
repo: factory
topic: human-rework-notes-reach-the-stage
status: proposed
supersedes: []
---

# Should a human's rework notes reach the stage the run is sent back to?

## Decision

Question for the owner: when you answer `rework` at an approval, module 8 says the run goes "to `on_reject.goto` with your notes as feedback". The engine routes the run back but does not pass the notes to the stage. How should they get there?

Recommended option: **write the notes into the target stage's tasks as a feedback record**, with a new optional `notes` field in `feedback.schema.json`, and leave the other feedback fields as they are. A human rework has no gate, exit code or failing tests, so those fields would hold the values the schema already allows for "none" (`gate: "human"`, `exit_code: null`, empty lists).

## Context

- Module 8's class table, row "Human rework": "Route to `on_reject.goto` with your notes as feedback" (`docs/design/modules/08-gates-error-handling-and-rework.md`, line 14). Module 11 lists `--notes` as part of every answer and says "Approve moves the run on. Rework sends it back with your notes" (`decisions.py`, the approval template packet).
- Checked by running (`factory/engine/tests/engine/test_human_rework_and_reject.py`): a real `rework` answer through `decisions.record` routes the run back to `root-cause`, starts a new visit and asks again, and the run's `feedback` folders stay empty. A reject aborts the run.
- Checked in the code: `Outcome.notes` is read only by `page.py` and `delivery.py` (`never_auto_if.notes_used`). `_human_stop` in `engine.py` calls `rework.route` with the outcome and never reads `notes`. `build_feedback` runs only for gate and join failures, and it logs `routed_back`, so a human rework logs no `routed_back` either.
- `feedback.schema.json` has `additionalProperties: false` and requires `gate`, `exit_code`, `failed_tests`, `output_tail` and `changed_files`. It has no field for notes.
- The prompt builder already shows every feedback record to the task (`prompt.py`, `ctx.feedback`), so a record written to the target stage's task folder would reach the worker with no prompt change.
- A note queued through `factory note` is a separate path: it is delivered to one running task (`notes.py`), not to a stage that starts again.

## Options considered

1. **A feedback record with a `notes` field (recommended).** For: uses the path the prompt already reads; the record shows the loop number and the stage it came from, like a gate rework; no new mechanism. Against: changes a state-file schema, which AGENTS.md lists as a decision for the owner; the other required fields hold placeholders for a human rework.
2. **Queue the notes as a note on each task of the target stage** (`notes.queue_note`). For: no schema change; the prompt already has "Notes from the operator". Against: a task reset deletes `task.json`, and the note API is built for a running task, so the note could be lost or delivered to the wrong attempt; it loses the "from stage, loop" context.
3. **Leave it as is and change module 8 to say the notes are not passed.** For: no code. Against: the answer's notes are the only way to say what to change, so a rework with no notes gives the worker nothing new and repeats the same work.

## Why

The notes are the content of a human rework. Without them the stage runs again on the same input, so the loop cannot end for a reason the person cares about. Option 1 reuses the one channel a worker already reads for rework, so it is the smallest change that makes the rework row true.

## Consequences

- If accepted: `feedback.schema.json` gains an optional `notes` string; `build_feedback` or a sibling writes the record for a human rework; `_human_stop` calls it; module 8's feedback example and the rework row say what the fields hold. The acceptance criterion "each failure type maps to exactly one handling type" can then be ticked, with the test as its evidence.
- If option 3: module 8's row changes and the criterion is ticked with the notes named as not passed.
- Until the owner answers, the criterion stays unticked, and the new test covers the routing (rework goes back and asks again; reject aborts) but not the notes.
- Supersedes: none.

## Source

`docs/design/modules/08-gates-error-handling-and-rework.md` (line 14 and the unticked criterion); `factory/engine/factory_engine/engine.py` (`_human_stop`); `factory/engine/factory_engine/rework.py` (`build_feedback`, `_route_outcome`); `factory/schemas/feedback.schema.json`; the test above, run 2026-11-22.
