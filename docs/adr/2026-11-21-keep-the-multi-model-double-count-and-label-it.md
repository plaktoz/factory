---
scope: repo
repo: factory
topic: keep-the-multi-model-double-count-and-label-it
status: accepted
supersedes: []
---

# An attempt with several models is counted under each, and the report says so

## Decision

Accepted by the owner on 2026-11-21, in the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them: keep the double count, and label it.

An attempt with several models is counted once under each model, with its full summed tokens and minutes. The model rows therefore add up to more than the real total. `factory usage` prints the by-model rows under the label "per model, an attempt with several models is counted under each", then one total row that counts each attempt once. `--json` carries the same `total`.

## Context

Module 14 said tokens are split as the harness reported them, but the record holds one summed count and no per-model split, so a split is not possible.

## Options considered

- **Keep the double count and label it (chosen).**
  - The walkthrough's option list is not in the repo, so no alternatives are listed. This record states the answer the owner gave.

## Why

A split would show numbers the harness did not report.

## Consequences

- `UsageReport` has a new `total` field, the only report field the spec did not list.
- Tests in `factory/engine/tests/usage/test_usage.py`: `test_an_attempt_with_several_models_is_counted_under_each`, `test_the_total_counts_an_attempt_with_several_models_once`, `test_factory_usage_labels_the_model_rows_and_prints_the_total`, `test_factory_usage_json_carries_the_total`.
- Commit `6a69067`, PR #73.

## Source

Written on 2026-11-21 by Claude Code from the owner's walkthrough answers on the gaps the revise-spec calibration found, as the session handoff of 2026-11-21 recorded them. The answer is the owner's, not new.
