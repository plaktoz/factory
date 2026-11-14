---
name: factory-reproduce
description: Write a failing test that shows a reported bug.
---

Find the code the report points at. Write the smallest test that fails because of the bug, and run it to confirm it fails for the stated reason. Write the artifact the task names, recording the test's path, the command that runs it, and its failing output.

The artifact's schema is `stage-report`, defined by module 5. Use the file name the task gives you.

## Rules for every factory skill

- **Never ask a question.** You run headless: nobody answers. If you need a person to decide, write a decision packet
  (see the architect skill's format) instead, and stop.
- **Read your inputs from the prompt** and the files it names. Do not browse for more unless the task allows it.
- **Write one artifact** to `$FACTORY_TASK_DIR`, with the file name the task gives you. Write nothing else there except
  `progress.md` (a short note of where you are, so a restart can resume) and the helpers ledger when the task allows helpers.
- **Never commit, push, merge or touch an issue.** The engine does every git and GitHub action.
- **Stay inside your scope.** Edit only the paths in your task's scope, and never the deny paths.
- **Start no subagents** except as the helper policy in your prompt allows.
