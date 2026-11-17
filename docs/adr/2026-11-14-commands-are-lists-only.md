---
scope: repo
repo: factory
topic: commands-are-lists-only
status: accepted
supersedes: []
---

# String commands in gates and join_cmd

## Decision

nine examples rewritten as lists; a string fails at load with `config.invalid`

Chosen option: `lists-only`.

## Context

Section 18 freezes GateSpec.cmd as list[str] and module 3 requires argument lists with no shell. Seven commands in module 5's YAML and one in module 4 are strings (`cmd: "make build"`), and module 7 writes `join_cmd: "npm install --package-lock-only"`. That is nine, and none uses shell syntax such as a pipe or &&.

## Options considered

- **`lists-only`** (chosen) (recommended): Rewrite the nine examples as argument lists and make a string an error at load
  - For: Matches module 3's no-shell rule and the frozen type
  - For: No parsing rule to document or get wrong
  - For: The schema check catches the mistake before a run
  - Against: Slightly noisier YAML: [make, build] for make build
  - Against: Repos copying the examples must use lists
- **`split-string`**: Accept a string and split it into words with shlex at load; still no shell
  - For: The short form in the examples stays valid
  - For: Still no shell is used
  - Against: A hidden rule: quotes and spaces in a path split in surprising ways
  - Against: The frozen type gains a second input form to test
- **`string-is-shell`**: A string runs through the shell, a list does not
  - For: Pipes and && work in a gate
  - Against: Contradicts module 3 and breaks Windows later
  - Against: Opens injection through request text that reaches a command

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

Nine examples are cheap to fix now, and a list keeps one meaning for the frozen type.

## Source

Backfilled on 2026-11-16 from `docs/reviews/open-decisions.md`, decision `Q3`, page `docs/reviews/open-items.json`. The owner chose this on 2026-11-14; the answer is the record's, not new.
