---
scope: repo
repo: factory
topic: a-running-claude-task-streams-its-log
status: accepted
supersedes: []
---

# A running Claude task streams its log

## Decision

Accepted by the owner on 2026-11-21, on page `.scratch/open-items.json`, decision `D3`: option `stream-log`. The page calls it "Show the task live".

The Claude adapter starts every worker with `--output-format stream-json --verbose`, not `--output-format json`. Each assistant message, tool call and tool result arrives as one event line while the worker runs. The adapter turns each event into plain text before it writes `worker.log` (`plain_log` in `factory_engine/adapters/worker/claude.py`):

- assistant text as it is
- a Bash call as `$ <command>`, any other tool call as `<tool>: <input as JSON>`
- a tool result as its text
- a `result` line with `is_error` true as `error: <text>`; a successful result adds no line, because its text repeats the last assistant message

A line that is not an event, such as a warning on stdout, is kept as it is. Raw events never reach `worker.log`. Tokens and model names still come from the stream's `result` line, which `parse_result` already found.

## Context

`worker.log` is written while a task runs (ADR `2026-11-17-worker-log-is-written-while-the-task-runs`). The Claude adapter ran with `--output-format json`, which prints one result object when the attempt ends. Checked on 2026-11-21 with Claude Code 2.1.330: counting from 1 to 5 printed 1 line of 1,713 bytes, all at the end. So a running Claude task showed only stderr, and the dashboard's live view was empty for most of a run. ADR `2026-11-18-a-silent-cmd-task-is-reported-not-killed` left Claude tasks out of the silence warning for this reason and called covering them a separate decision.

Facts checked by running the CLI on 2026-11-21 (Claude Code 2.1.330, `--setting-sources project`, as the adapter runs it):

- `stream-json` with `-p` needs `--verbose`. Without it the CLI exits with "When using --print, --output-format=stream-json requires --verbose".
- The stream's last line has `type: result` and carries `modelUsage`, keyed by the model name the gateway returned. The token and model parsing needs no change.
- A run that calls Bash (`sleep 6; echo finished`) printed lines at 0.5 s (init), 5.4 s and 5.6 s (assistant messages and the tool call), 10.2 s, 13.3 s (tool result) and 15.5 s (final message and result). Between 5.6 s and 10.2 s the quiet tool call printed nothing.
- A one-line answer was 6,154 bytes in stream mode against 1,713 bytes in `json` mode. With personal settings loaded, a plain `claude -p` stream was 58,413 bytes, because its init and `commands_changed` events list every skill. `--setting-sources project` keeps the init event small, and the adapter does not write init events to `worker.log`.

## Options considered

- **`stream-log`** (recommended, chosen): stream, and render each event as plain text.
  - For: you see progress, and can tell a working task from a stuck one.
  - For: tokens and model names are still reported; checked.
  - For: makes the silence warning possible for Claude tasks later.
  - Against: bigger capture files for every Claude task.
  - Against: a long quiet tool call still adds no line, so a silence warning on Claude tasks would need a higher limit than the 10 minutes `cmd` tasks use.
  - Against: the adapter now depends on the stream's event shapes (`assistant` and `user` messages with `text`, `tool_use` and `tool_result` parts), not only on the final result.
- **`keep-final-only`**: keep `--output-format json`.
  - For: no change and no new format to depend on; small logs.
  - Against: a hung task looks the same as a working one until its time limit ends it.
  - Against: most factory work is Claude tasks, so the live view stays empty for most of a run.

## Why

Most of a run is Claude tasks. The result reading and token counts already worked on a stream, so the cost is the bigger capture file and one plain-text renderer.

## Consequences

- `claude.py`: workers use `FLAG_STREAM`; `FLAG_OUTPUT` is removed. `plain_log` renders stdout for both the live tail and the final log. The doctor probe already streamed.
- Module 9's flag table, model flow, Live log text and a new acceptance criterion; module 12, step 1; the phase 2 comparison table. The machine-file example no longer passes `--output-format json` in `args`, since the adapter drops any `--output-format` it finds there.
- Tests: four new tests in `factory/engine/tests/workers/test_claude_adapter.py` and the fixture `recorded/stream.jsonl`, recorded from the real CLI with its init event trimmed (no local paths, tool list or session id).
- Not built: the silence warning for Claude tasks. `stall_minutes` and `task_silent` are not built for `cmd` tasks yet either (ADR `2026-11-18-a-silent-cmd-task-is-reported-not-killed`). Extending them to Claude, with a limit that allows a quiet tool call, is a separate change.
- Not checked: a live factory run with a real Claude worker. The tests use the stub, which replays the recorded stream.
- Task: item 21 in `docs/tasks.md`.

## Source

Written on 2026-11-21 by the session that built it, from the owner's pasted answer to page `.scratch/open-items.json`, decision `D3`. The page is a working copy in `.scratch/` and is removed once its decisions are recorded, so the options above are copied from it.
