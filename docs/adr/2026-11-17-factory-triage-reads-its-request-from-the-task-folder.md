---
scope: repo
repo: factory
topic: factory-triage-reads-its-request-from-the-task-folder
status: accepted
supersedes: []
---

# `factory triage` reads its request from the task folder

## Decision

Accepted by the owner on 2026-11-17: option `copy-request-into-task-folder`. Before a `cmd` task starts, the engine copies the run's `request.json` into that task's `work/` folder. `factory triage` reads `$FACTORY_TASK_DIR/request.json` and writes `$FACTORY_TASK_DIR/triage.json`.

## Context

The shared `_triage` workflow starts every run with `{id: rules, cmd: [factory, triage], out: triage.json}`. Module 4 says the command reads the run's request and writes `triage.json`. Module 9 says every `cmd` task runs under `srt` with the worker's read rules.

Those two rules collide. `srt` denies reads of the factory home, and a run's `request.json` is at `<factory home>/runs/<repo key>/<run id>/request.json`. The only readable paths are the task's own `work/` folder and the worktree (`sandbox.deny_read`, `sandbox.allow_read`). A `rules` task also has no git worktree: the engine gives it an empty `work/` folder, so the launcher's `find_repo` cannot find a repo from the current folder.

Checked by reading `factory_engine/adapters/worker/sandbox.py` and `engine.py` (`_start_task`, `_context`) on 2026-11-17. Not run: no `cmd` task has run under `srt` through the engine yet.

## Options

- **`copy-request-into-task-folder`**: Before it starts a deterministic task, the engine copies `request.json` into that task's `work/` folder. `factory triage` reads `$FACTORY_TASK_DIR/request.json` and writes `$FACTORY_TASK_DIR/triage.json`.
  - For: The sandbox rules stay as module 9 and decision D7 state them. The command needs no access to the factory home, a run lookup or a git repo.
  - For: The engine already owns the task folder and writes into it for every task.
  - Against: One more file in each task folder, and the engine must decide which tasks get it. The simple rule is every `cmd` task.
  - Against: The copy can go stale if the request changes after the task starts. A triage task is short, so this is a small risk.
- **`allow-read-request-in-sandbox`**: Add the run's `request.json` to the `srt` allow-read list for `cmd` tasks.
  - For: No copy. The command reads the real file.
  - Against: It changes the sandbox rules, which module 9 and D7 define. It exposes a path under the factory home to every command.
  - Against: The command still needs the run id and the factory home to find the file, so the environment needs both.
- **`pass-request-on-stdin`**: The engine writes the request as JSON to the command's stdin.
  - For: No file and no sandbox change.
  - Against: `CommandAdapter` gives a `cmd` task no stdin today (it is `DEVNULL`; only a plugin Python task gets stdin), so this changes the adapter's contract and every command's behavior.

## Recommendation

`copy-request-into-task-folder`. It keeps the sandbox boundary where D7 set it and needs no change to the adapter's stdin rule.

## Consequences if accepted

- `factory triage` becomes a command that needs only `FACTORY_TASK_DIR`. It loads no config and no run.
- Module 4 and module 16 each need one sentence naming the file.
- A test asserts the command, run under the real `CommandAdapter`, writes a `triage.json` that the `type-resolved` gate accepts.
