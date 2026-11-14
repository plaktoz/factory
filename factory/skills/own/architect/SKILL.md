---
name: factory-architect
description: Write a decision packet when a choice needs a person.
---

Use this when the task needs a human choice, such as a framework or a data model. Write a decision packet that matches the `packet` schema: a `stage`, then one entry per decision with `id`, `title`, `question`, `context` (`what`, `example`, `terms`), `compare` (`a`, `b`, `rows`, `choose_a_if`, `choose_b_if`), `recommend`, `why` and 2 to 4 `options` (each with `id`, `name`, `flow`, `pros`, `cons`).

The packet schema requires every field a picker shows, so leave none out: a packet missing context or flows fails its gate.

## Rules for every factory skill

- **Never ask a question.** You run headless: nobody answers. If you need a person to decide, write a decision packet
  (see the architect skill's format) instead, and stop.
- **Read your inputs from the prompt** and the files it names. Do not browse for more unless the task allows it.
- **Write one artifact** to `$FACTORY_TASK_DIR`, with the file name the task gives you. Write nothing else there except
  `progress.md` (a short note of where you are, so a restart can resume) and the helpers ledger when the task allows helpers.
- **Never commit, push, merge or touch an issue.** The engine does every git and GitHub action.
- **Stay inside your scope.** Edit only the paths in your task's scope, and never the deny paths.
- **Start no subagents** except as the helper policy in your prompt allows.
