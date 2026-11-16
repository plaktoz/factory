---
name: factory
description: Chat front end for the factory. Use when the user asks to run a bug-fix or chore on an issue, check on runs, see what needs them, or answer a decision. Maps phrases to the factory CLI, shows decision packets as pickers, and answers through `factory decide`. Never writes state or starts workers.
---

Map the user's words to one `factory` command, run it, and report what it printed. The CLI owns the state and the engines. This skill adds no other path.

## Rules

- Run only the commands below. Never edit `.factory/`, `run.json`, `task.json`, `decisions/` or any other state file.
- Never start a worker or an engine by hand. A command that needs an engine starts it. `factory decide` starts one when the answer moves a run.
- Show the CLI's message as it is. Quote its `code` and `hint` when it fails.
- If the chat ends, the run goes on. Nothing here holds a lock.

## Phrase to command

| The user says | Run |
| --- | --- |
| "run bug-fix on issue 42", "fix this bug" | `factory add "<title>" --type bug --body <file>`, then `factory run <run-id>` |
| "do this chore", "bump X" | `factory add "<title>" --type chore`, then `factory run <run-id>` |
| "sync the issues and inbox" | `factory sync` |
| "what is running", "status" | `factory status` (add the run id for one run) |
| "what needs me", "inbox" | `factory inbox` |
| "show the decision" for a run | `factory check <run>`, then render the picker below |
| "answer D1 with opt-a" | `factory decide <run> --packet <sha> --choice D1=opt-a` |
| "ask about D2 before deciding" | `factory decide <run> --packet <sha> --question D2="<text>"` |
| "retry the stage", "try again" | `factory retry <run> --note "<text>"` |
| "send it back to <stage>" | `factory goto <run> <stage>` |
| "skip the lint gate, reason" | `factory skip <run> --gate <gate> --reason "<text>"` |
| "stop this run" | `factory abort <run> --reason "<text>"` |
| "tell the coder <note>" | `factory note <run> <task> "<text>"` |
| "where is the run folder" | `factory where <run>` |
| "what has it done" | `factory events <run> --tail 20` |
| "how many tokens" | `factory usage <run>` |
| "clean up old runs" | `factory gc` (the plan), then `factory gc --apply` only when the user says so |

Every command takes `--repo <path>` when the run is not in the current folder. A run id alone is enough, because the CLI reads the repo from the run's record.

## Decision packets

When `factory inbox` or `factory check` names a stop, read the packet from the decision file the CLI names. Show each decision in the picker format: the question, the context, the two options with their pros and cons, and the recommended one marked.

Answer through `factory decide` with the packet sha the page shows:

```
factory decide <run> --packet <sha> --choice D1=<option-id> --choice D2=<option-id>
```

If the CLI refuses with `decision.stale_packet`, the packet changed. Show the new packet and ask again. Do not retry the old sha.

If the CLI refuses with `decision.bad_choice`, name the option ids the packet offers and ask again.

## Exit codes

The CLI exits 0 for ok or done, 1 for failed, 2 for invalid input, 3 when a human must answer, 4 when a run is blocked, and 5 when another engine holds the run. Report the code in plain words. For 3, point to the inbox. For 4, say the run is blocked and offer `retry`, `goto`, `skip` or `abort`. For 5, say another engine is working on it and that nothing was started.
