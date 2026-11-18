---
scope: repo
repo: factory
topic: worker-log-is-written-while-the-task-runs
status: accepted
supersedes: []
---

# `worker.log` is written while the task runs

## Decision

Accepted by the owner on 2026-11-18: option `tail-the-capture-while-running`. While a worker runs, the engine's wait loop copies each complete new line of the capture files into `worker.log` about once a second, masked. The end-of-attempt write stays, so the finished log is the same as before. The Claude, Codex and command adapters all use one helper, `LogTail` with `wait_tailing`, in `adapters/worker/runtime.py`.

## Context

Module 12 says the adapter writes the worker's output to `tasks/<id>/worker.log`, and the dashboard shows the last 200 lines for each running task. In the code, none of the three adapters does that.

Checked by reading the adapters on 2026-11-17. Not run against a live worker.

- `CommandAdapter` sends stdout and stderr to two files in the task folder and copies both into `worker.log` in `_finish_log`, after the process exits (`command.py`, lines 110 to 151).
- `ClaudeAdapter` and `CodexAdapter` do the same: capture files while the worker runs, then `write_log` once the attempt ends (`claude.py` line 337, `codex.py` line 311).

So a task that runs for 20 minutes has no `worker.log` until it ends, and the live view shows nothing. A person cannot tell a working task from a stuck one. A 21-minute test suite run through a `cmd` task would look the same way.

The two files exist for a reason. `srt` confines a child's writes to the worktree and the task folder, so the capture files sit in the task folder. The log is parsed from them after the end: Claude and Codex emit an event stream (JSON lines) that `plain_log` turns into text, and secrets are masked before the text is written (`write_log` calls `mask`).

## Options

- **`tail-the-capture-while-running`** (chosen): While the process runs, the engine's wait loop copies new bytes from the capture file into `worker.log` every second or so. The command adapter copies the text as it is. The Claude and Codex adapters run the same event-to-text step on each new complete line. Secrets are masked on each chunk. The end-of-attempt write stays as the final, full version, so the finished log is the same as today. Cost: a masking rule that works on whole lines only, and a small loop in each adapter's `wait`. Checked on 2026-11-17: `mask` applied to two halves of `token=sk-ABCDEF123456 end` leaves the secret in plain text, while `mask` on the whole line gives `token=*** end`. So the copy must hold back a partial last line until its newline arrives. A secret that contains a newline is still a gap.
- **`command-adapter-only`**: Change only `CommandAdapter`, where the output is plain text and the change is small. Claude and Codex logs stay end-of-attempt. This fixes the 21-minute-suite case and leaves the live view empty for the longest workers, which are the model-driven ones.
- **`leave-as-is-and-fix-the-spec`**: Change module 12 to say the log appears when the attempt ends. Nothing is built. A person watches a running task through `progress.md` and the events file only.

## Consequences

If the first option is accepted, the work is: a shared helper in `runtime.py` that copies new complete lines and masks them; the three adapters call it from `wait`; one test per adapter that reads `worker.log` before the task ends; and one test that a secret split across two chunks is masked. Module 9 and module 12 get a line each.

Found while building, 2026-11-18: the Claude adapter runs with `--output-format json`, so its stdout is one result line that arrives when the attempt ends. For a Claude worker the live log therefore shows stderr as it arrives and the result line at the end, not a stream of agent messages. The Codex and command adapters stream as the ADR describes. Showing Claude's messages while it runs needs `--output-format stream-json`, which changes how the result and the token counts are read. That is a separate decision and is not made here.

Checked: `tests/workers/test_log_tail.py` (the helper: partial lines, a secret split across two writes, a multi-byte character cut by a write, timeout) and one test per adapter that reads `worker.log` while the worker is still running. With `LogTail.poll` disabled, the three adapter tests fail.
