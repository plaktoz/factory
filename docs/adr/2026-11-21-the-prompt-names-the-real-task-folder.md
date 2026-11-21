---
scope: repo
repo: factory
topic: the-prompt-names-the-real-task-folder
status: accepted
supersedes: []
---

# The worker's prompt names the real task folder

## Decision

The owner chose option 1 on 2026-11-21: the prompt's output instruction gives the absolute path of the task folder, for the artifact, `progress.md` and the ledger. It still says the folder is `$FACTORY_TASK_DIR`.

The fix is in `prompt.py`, `build_prompt`. Two tests that checked for the literal text `$FACTORY_TASK_DIR/<file>` now check for the absolute path, and a new test checks all three files.

## Why

In a real run on a scratch repo (2026-11-21), the Claude worker of the `chore` workflow's `change` task wrote the correct code change three times and never wrote `change.json`. All three attempts were discarded and the run blocked. The worker's log said it could not write its output and could not read `$FACTORY_TASK_DIR`, because it had no Bash to run `echo`.

The prompt told the worker to write to the literal text `$FACTORY_TASK_DIR/change.json`. A worker with the tools Read, Edit, Write, Glob and Grep cannot expand an environment variable, so it never learned the real path. The sandbox was not the cause: its rules allow the task folder, and the folder was writable.

Checked: one real `claude -p` call with the absolute path in the prompt and the same tools wrote its file. After the fix, a rerun of the same request succeeded on the first attempt, and `change.json`, `progress.md` and `helpers.jsonl` were in `tasks/change/work/`.

## Options considered

- **`real-path-in-prompt`** (chosen, option 1). Put the absolute path in the prompt.
  - For: A small change. It fixes the cause that was found, and it needs no change to the worker's tools.
  - Against: The prompt now varies with the run, so two runs of the same task give different prompt text. Tests that compare prompts must pass the same folder.
- **`engine-runs-the-tests`** (option 2). The engine runs the tests and writes `change.json`, and the worker writes code only.
  - For: The worker needs no Bash.
  - Against: It changes how the implement stage works, and the real cause was the missing path, not the missing Bash. Not chosen, because the first fix may be enough.
- **`grant-bash`** (option 3). Give the implementation tasks Bash.
  - Against: It widens the sandbox. Not chosen.

## Consequences

- The worker still has no Bash in the `chore` workflow (`engine.py` sets `bash=[]`). The implement skill asks the worker to run the tests, and it cannot. The `verify` stage runs `scripts/check`, so the run is still checked, but the worker cannot check its own work. Whether that needs option 2 later is open.
- The prompt text differs between runs, because it holds a path.

## Source

Found by building the tutorial on 2026-11-21 and running it on a scratch repo. Chosen by the owner in the session that found it.
