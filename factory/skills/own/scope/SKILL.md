---
name: factory-scope
description: Turn a research request into focused questions.
---

Read the request and list the questions that, answered, would satisfy it. Group them, drop duplicates, and mark any that need a source the factory cannot reach.

The artifact is `questions.json`: a JSON array with one item per question, each `{"id": "q1", "question": "..."}`. Ids start with a lower-case letter or digit, then use lower-case letters, digits, hyphens or underscores, and each is unique. Write the question in plain words; the person confirming the list reads it as it is. Do not add task settings such as a skill or a timeout: the workflow's `task_template` sets those.

## Rules for every factory skill

- **Never ask a question.** You run headless: nobody answers. If you need a person to decide, write a decision packet
  (see the architect skill's format) instead, and stop.
- **Read your inputs from the prompt** and the files it names. Do not browse for more unless the task allows it.
- **Write one artifact** to `$FACTORY_TASK_DIR`, with the file name the task gives you. Write nothing else there except
  `progress.md` (a short note of where you are, so a restart can resume) and the helpers ledger when the task allows helpers.
- **Never commit, push, merge or touch an issue.** The engine does every git and GitHub action.
- **Stay inside your scope.** Edit only the paths in your task's scope, and never the deny paths.
- **Start no subagents** except as the helper policy in your prompt allows.
