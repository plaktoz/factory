---
name: factory-implement
description: Build a new feature or application in the task's scope.
---

Follow the approved plan and the architecture decision. Write the code and its tests in your scope. You cannot run commands, so do not try to run the tests or the build: the verify stage runs them after you finish, and a failure there sends the run back to this stage for another attempt. Keep the change small and reviewable.

The artifact's schema is `stage-report`, defined by module 5.

## Rules for every factory skill

- **Never ask a question.** You run headless: nobody answers. If you need a person to decide, write a decision packet
  (see the architect skill's format) instead, and stop.
- **Read your inputs from the prompt** and the files it names. Do not browse for more unless the task allows it.
- **Write one artifact** to `$FACTORY_TASK_DIR`, with the file name the task gives you. Write nothing else there except
  `progress.md` (a short note of where you are, so a restart can resume) and the helpers ledger when the task allows helpers.
- **Never commit, push, merge or touch an issue.** The engine does every git and GitHub action.
- **Stay inside your scope.** Edit only the paths in your task's scope, and never the deny paths.
- **Start no subagents** except as the helper policy in your prompt allows.
