# 12. Module: live view and steering

Part of the [phase 1 design](../phase-1.md#module-map). Build wave: 2. Contracts and acceptance criteria are in this file; shared types are in [section 18](../shared/18-shared-contracts.md). Terms such as run, stage, task, attempt and rework are defined in the [glossary](../phase-1.md#2-glossary).

You watch any running task through its live log and steer it with notes, which the engine delivers at the next checkpoint. Workers stay headless, so results stay repeatable.

1. The adapter writes the worker's output to `tasks/<id>/worker.log`. The dashboard shows the last 200 lines for each running task.
2. You send a note with `factory note <run>/<task> "text"` or the Add note box. The engine appends it to `notes.jsonl` as queued.
3. At the next checkpoint, the engine stops the worker and starts a new attempt. The new prompt carries `progress.md`, every delivered note and the scope reminder. Each restart counts toward `max_restarts`.
4. For a hard rule, add a deny path: `factory note <run>/<task> --deny "auth/**" "text"`. The scope check then fails any edit there, whether or not the worker follows the note.

- A restart ends any helper sessions, so helpers are started again from the ledger.
- A note restarts the worker with `progress.md`, the same path as crash recovery. Resuming the harness's own session with the note appended is not used in phase 1; an adapter can add it later without changing how notes are stored or delivered.
- Before a restart that delivers a note, the engine formats the task's files and makes a final WIP commit, so the restart loses no work.
- Notes are kept with the task artifacts for audit.
- A run where notes were used is never auto-merged ([module 13](13-delivery.md)).
- A note waits for the next checkpoint, so set `checkpoint_every_minutes` short for risky tasks. Takeover on demand (pause, attach, hand back) is planned for later and needs no change to checkpoints.

**Module contract: 12 Live view and steering**

- **Depends on:** 6A: `task_dir`, `read_task`, `append_event`.
- **Writes:** `notes.jsonl`; events `note_queued`, `note_delivered`. A note's deny paths are stored with the note and applied to the task by 6B, so 7's scope check reads them from the task state. The restart itself is done by 6B.
- **CLI it backs:** `note`; the log tail for the dashboard.

```python
# notes.py
def queue_note(run_dir: Path, task_id: str, text: str, *, deny: list[str] | None = None,
               by: str) -> NoteRef                     # refuses a finished task: notes.task_finished
def pending_notes(run_dir: Path, task_id: str) -> list[Note]
def mark_delivered(run_dir: Path, task_id: str, note_ids: list[int], *, attempt: int) -> None
def delivered_notes(run_dir: Path, task_id: str) -> list[str]     # for the prompt, oldest first
def tail_log(path: Path, lines: int = 200) -> str
```

- **Run and test:** `pytest factory/engine/tests/notes`; `factory note <run>/<task> "text" --json`.
- **Errors:** a note for a finished task is refused. When the restart cap is reached, the note stays queued and 6B raises an attention item. A log parser failure keeps the raw output.

Acceptance criteria:

- [ ] A queued note is pending until `mark_delivered`, then appears in every later prompt.
- [ ] A note with `--deny` makes the scope check fail on a later edit in that path.
- [ ] A note for a done task is refused with a clear message.
- [ ] `tail_log` returns the last lines without reading the whole file into memory.
