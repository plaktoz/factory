---
name: factory-classify
description: Decide the type of a request (bug, feature, chore, research, new-app) when the rules could not.
---

Read the request in the prompt. Choose one type from the list the prompt gives. Write `triage.json` with these fields: `schema_version` (1), `type`, `workflow`, `confidence` (0 to 1) and `type_source` (the string `llm`).

If you are not sure, lower the confidence: below 0.8 the engine asks a person. Never guess a high confidence.

## Rules for every factory skill

- **Never ask a question.** You run headless: nobody answers. If you need a person to decide, write a decision packet
  (see the architect skill's format) instead, and stop.
- **Read your inputs from the prompt** and the files it names. Do not browse for more unless the task allows it.
- **Write one artifact** to `$FACTORY_TASK_DIR`, with the file name the task gives you. Write nothing else there except
  `progress.md` (a short note of where you are, so a restart can resume) and the helpers ledger when the task allows helpers.
- **Never commit, push, merge or touch an issue.** The engine does every git and GitHub action.
- **Stay inside your scope.** Edit only the paths in your task's scope, and never the deny paths.
- **Start no subagents** except as the helper policy in your prompt allows.
