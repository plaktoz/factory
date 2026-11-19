---
scope: repo
repo: factory
topic: wire-commands-next
status: accepted
supersedes: []
---

# Real bug-fix runs come before the rest of module 16

## Decision

The next change makes a real run work end to end: `cmd` steps, `cmd` gates and the report wiring. The remaining module 16 criteria come after it.

Chosen option: `wire-commands-next`.

## Context

On 2026-11-17 a real run could not work as designed. Every run starts with a command step (the rules that pick bug-fix or chore), and the factory handed that command to Claude instead of running it. A `cmd` gate such as "make build" stopped with "a cmd gate needs module 9's CommandAdapter, which is not built". Both were checked by running the engine. The tests passed only because they use a stand-in runner. The work is item 12 of `docs/tasks.md`.

## Options considered

- **`wire-commands-next`** (chosen, recommended): the wiring goes first, so the pilot gets a real run to watch sooner. Cost: the four open module 16 items (watch command, two kit versions, live-lock tests, PR polling) move later, and the change touches the engine loop, so it needs the full suite before merge.
- **`finish-module-16-first`**: close module 16's open items, then wire commands. Cost: no real run until both are done, so the pilot waits longer; PR polling needs real runs to be tested well.

## Source

Answered on 2026-11-17 on page `746ec67:docs/reviews/test-results-decisions.json` (the folder was deleted after that commit), decision `T2`, option `wire-commands-next`, which was the recommended option. The owner's answer is the record's, not new.
