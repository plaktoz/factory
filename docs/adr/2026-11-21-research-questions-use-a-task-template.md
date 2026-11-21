---
scope: repo
repo: factory
topic: research-questions-use-a-task-template
status: accepted
supersedes: []
---

# The research question list is plain questions, with a task template

## Decision

Accepted by the owner on 2026-11-21, on page `.scratch/open-items.json`, decision `D2`: option `plain-questions`. The page calls it "Plain questions plus a template".

A stage that uses `tasks_from` may name a `task_template`, a set of task fields such as `skill`, `helpers` and `timeout_minutes`. The artifact the earlier task writes is then a list of plain questions, `[{"id": "q1", "question": "..."}]`. The engine builds one task per item: the template, then the item's own fields, with the question left out. An item may override any template field. The question is written into that task's prompt under "Your question". A template is checked as a task when the workflow loads. A question list on a stage with no template is refused, and a template on a stage with no `tasks_from` is refused.

The research workflow's `scope` step writes `questions.json` in this form. The `gather` stage reads it with `task_template: {skill: gather, helpers: {mode: off}, timeout_minutes: 20}`.

## Context

Checked by running the code on 2026-11-21:

- Before this change, `tasks_from` accepted only a list of full task objects. A plain question list was refused: `item 0: (top level): Additional properties are not allowed ('question' was unexpected)`.
- The spec's research example did not load. Its `task_template` key was rejected: `Additional properties are not allowed ('task_template' was unexpected)`.
- The `scope` skill's text said `questions.json` follows the `source-notes` schema. That schema describes what a gather task writes, not a question, so the file had no correct schema. Module 5 recorded this as open.
- Research is phase 1b. No shipped workflow uses `tasks_from` except the reviewer eval's `languages` tasks in module 17A, which the engine does not call yet. No run is affected today.

## Options considered

- **`plain-questions`** (recommended, chosen): a question list plus a template in the workflow.
  - For: what the person approves is a short, readable list of questions. Nobody edits skills or timeouts in the approval.
  - For: the research example in module 5 loads as written, checked.
  - For: one place sets the gather skill and limits, so a change to them applies to every question.
  - Against: a new key in the workflow rules, and a second place to look (the template and the item).
  - Against: a question that needs its own skill cannot express that unless the item overrides the template.
- **`task-objects`**: keep the full task entries, and have the scope skill write every setting.
  - For: nothing new to build; the engine already works this way.
  - For: a single question can carry its own skill or timeout.
  - Against: the approval shows task settings, not questions, so the person checks the wrong thing.
  - Against: the scope step must get every setting right for every question. One wrong setting stops the stage before any worker starts.
  - Against: the spec's research example still needs its `task_template` line removed, so it stops describing the design.

## Why

The approval stop exists so that a person checks the questions. A plain list is the only form that shows just the questions, and the template keeps the task settings in one place.

## Consequences

- `workflow.schema.json`: stage property `task_template` (an object), and `dependentRequired` so a template needs `tasks_from`.
- `workflow.py`: `Stage.task_template` is read at parse time; `expand_tasks_from` builds tasks from the template; `_template_problems` checks each template as a task at load; `questions_of` gives the question text to the engine.
- `types.py` and the module 5 `Stage` block: the field is added as the last field of `Stage`, so the spec-contract parser sees it.
- `base.py` and `prompt.py`: `TaskContext.question` is optional, and the prompt shows it when set. `engine.py` passes it.
- `factory/skills/own/scope/SKILL.md`: the scope skill writes the question list.
- Module 5 and the research example; module 5's acceptance criteria gain one line with its tests.
- Tests: seven in `factory/engine/tests/workflow/test_workflow.py`, one in `test_prompt_and_ledger.py`. All pass with the workflow and prompt tests (99 passed).
- Not built: the research workflow itself (phase 1b), and an engine-level test that runs a templated stage from start to finish. The engine reads the artifact from `tasks/<tasks_from>` in the run folder, while the scope task writes it into its own task folder. Module 5's `tasks_from` takes a path, so the join between the two is a separate change (see `docs/tasks.md`, item 19).
- Task: item 19 in `docs/tasks.md`.

## Source

Written on 2026-11-21 by the session that built it, from the owner's pasted answer to page `.scratch/open-items.json`, decision `D2`. The page is a working copy in `.scratch/` and is removed once its decisions are recorded, so the options above are copied from it.
