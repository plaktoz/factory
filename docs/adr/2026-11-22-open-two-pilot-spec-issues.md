---
scope: repo
repo: factory
topic: open-two-pilot-spec-issues
status: accepted
supersedes: []
---

# The spec pilot uses two issues the session opened: a merge record schema and seven cleanup tests

## Decision

Accepted by the owner on 2026-11-22, on the page "Pilot start and the push" (`.scratch/pilot-and-push.json`, since deleted; its answers are in these records), decision `D1`: option `open-two-issues`, the recommended option. The session opened two issues on `plaktoz/factory`, each in the Spec form:

- **#88** "Give merge.json a checked format". Adds `factory/schemas/merge.schema.json`, which `evaluate_merge` writes its output against.
- **#89** "Test seven open cleanup criteria in module 17". Adds tests for seven of the nine unticked criteria in `docs/design/modules/17-housekeeping.md`. Lines 121 and 128 are left out, because each needs a decision first.

Both are medium sized by the session's estimate, not measured. The owner names them as the pilot tickets in `docs/setup/spec-workflow-pilot.md`, and approval of each spec is the first step of a pilot run.

## Context

The repo had one open issue, #56, which is the research behind the pilot and not a ticket to build. Two real gaps were found by running commands on 2026-11-22:

- `factory/schemas` has 17 files, and none is for `merge.json`. `evaluate_merge` in `factory/engine/factory_engine/delivery.py` writes it from a dict, with keys `auto`, `reason`, `ci` and `rules`.
- `scripts/docs-check/criteria.py . 17` lists nine unticked criteria in module 17. Lines 121 and 128 need an owner decision: line 121 contradicts the crash behavior in lines 103 and 104, and line 128 says the owner decides which `worker.log` rule holds.

The spec form `.github/ISSUE_TEMPLATE/spec.yml` is on `origin/main` (blob `85b0dfe`), so GitHub renders it for these issues.

A correction made while opening #88: its first draft said `merge` has no dataclass. It does have `MergeDecision` in `delivery.py`; that dataclass is not the file, and the body now says so.

## Options considered

- **`open-two-issues`** (chosen, recommended): the session opens two issues, and the owner approves each spec.
  - For: both are real work with a clear finish line, and nobody has started them.
  - Against: they are public issues on the owner's account, and the size is an estimate.
- **`name-your-own`** (not chosen): the owner writes two issue numbers.
  - For: the owner picks work they care about.
  - Against: the repo has no open ticket today, so the owner would have to write them first.
- **`postpone-pilot`** (not chosen): the pilot waits.
  - For: no commitment while the tutorial and the open pull request are in progress.
  - Against: the agent rules stay untested, and the later decision has no date.

## Why

The pilot tests the spec steps on work the project needs anyway, and both issues have a finish line that makes review time and defects countable.

## Consequences

- **Done:** #88 and #89 are open, with the Spec form's four fields filled in.
- **Not done:** the work in either issue. The pilot's rule is that the owner approves each spec in a comment before code is written, so nothing is built yet.
- **Task:** `docs/tasks.md` item 37 is updated to name these issues; the baseline and start day stay open for D2 and the owner.

## Source

Written 2026-11-22 by the Claude Code session that applied the owner's answer (run `d5c2b949-b212-4992-9a5c-6284ed60de53`), from the page `.scratch/pilot-and-push.json`, decision `D1`.
