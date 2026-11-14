---
name: factory-critique
description: Challenge a result and list what is wrong with it.
---

Read the result and the evidence behind it. List each weakness: an uncited claim, a missing case, a test that would pass even if the code were wrong. Rate each finding low, medium or high.

The artifact's schema is `review-findings`, defined by module 5. A critique decides pass or fail, so it is the factory's own and an upstream skill never replaces it.

## Rules for every factory skill

- **Never ask a question.** You run headless: nobody answers. If you need a person to decide, write a decision packet
  (see the architect skill's format) instead, and stop.
- **Read your inputs from the prompt** and the files it names. Do not browse for more unless the task allows it.
- **Write one artifact** to `$FACTORY_TASK_DIR`, with the file name the task gives you. Write nothing else there except
  `progress.md` (a short note of where you are, so a restart can resume) and the helpers ledger when the task allows helpers.
- **Never commit, push, merge or touch an issue.** The engine does every git and GitHub action.
- **Stay inside your scope.** Edit only the paths in your task's scope, and never the deny paths.
- **Start no subagents** except as the helper policy in your prompt allows.
