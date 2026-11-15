# Wave 3 decisions: triage notes

Page: `docs/reviews/wave3-decisions.html`. Data: `docs/reviews/wave3-decisions.json`.

## Settled without the owner (checked by command)

| Item | Check | Result |
| --- | --- | --- |
| Shipped `max` values against the loop rule | `test_the_shipped_workflows_max_values_are_loops_allowed_so_max_2_routes_twice_then_blocks` | Passes. The code and the shipped files agree. Only the walkthrough differs (D2). |
| `bug-fix` no longer fails at run time with `config.invalid` | `test_bug_fix_no_longer_fails_with_config_invalid_at_its_schema_and_check_gates` | Passes. |
| Module 13 threshold for "blocking" | `review_findings_at_or_above: medium` in module 13 and in the merge-policy schema | Consistent with medium-or-high blocking. Applied, not asked again. |
| Waves 1 and 2 ticks cite real tests | Script over 184 ticked citations | 0 missing (PR #38). |
| Links | `links.py` | 223 links, 0 broken. |
| `docs/` in `factory/` | Grep over `factory/` | Only `delivery.py` names `docs/adr` and `docs/research` as target-repo paths. It is listed under D1's context, not a finding. Recorded as a rule ruling still needed: see the open question below. |

## Not asked (owner-only, no command can settle)

- **Commit `6a6ff04` email.** Removing it needs a force push, which is not approved. Left as is. Reported in `docs/tasks.md`.
- **`scope` skill vs `tasks_from`.** The `scope` skill says `questions.json` has the `source-notes` schema, but `tasks_from` reads it as a task list. No schema is drafted for `questions.json`. The settled fix is to say so in the skill text; a follow-up task, not a card.
- **`every-claim-has-source`.** Unbuilt because the spec does not say how a claim is matched to a source. Stays a task until the spec defines it.

## Open question for the `docs/` rule

`delivery.py` writes ADRs to `docs/adr/` and research reports to `docs/research/` in the **target** repo, as module 7 and 13 specify. AGENTS.md says `factory/` must not reference this repo's `docs/`. These are different `docs/` folders, so the code does not break the rule, but a literal grep does match. Resolve by adding a line to AGENTS.md that says so, or by moving the two constants to a config key. Not put on the page: the owner can settle it in one word when reviewing.

## Owner's answers (applied 2026-11-15)

| Decision | Choice | Recommended? | Applied in |
| --- | --- | --- | --- |
| D1 Draft report schemas and `merge.json` | `accept-drafts` | Yes | `factory/schemas/{stage-report,test-report,source-notes,review-findings}.schema.json` (draft marker removed); module 3 and module 5 (Report schemas); `docs/tasks.md` |
| D2 Loop count on `bug-fix` verify to fix | `raise-to-3` | No | `factory/workflows/bug-fix.yaml`; module 5 `bug-fix` example; module 8 stage-strip example and wave 2 note; `test_rework.py`; `docs/tasks.md` |
| D3 Phase 2 evals on `main` | `keep-both` | No | `docs/design/phase-2.md` (P2-9, what landed and what is open); `docs/tasks.md` |

D3 carries a cost the owner accepted: the kit copies `reviewer-eval.yaml` into every repo that runs `factory init`. The ADR lists this under "Known limits".

## PR #43 (answered 2026-11-15)

**PR #43, Codex worker adapter (P2-1).** Decided on `pr43-codex-decisions.html`: D1 `accept-both-codex-only` (both changes accepted for Codex workers only, recorded in D7 as residual risk in [module 9](../design/modules/09-worker-adapters-and-governed-helpers.md)); D2 `hold-resolve-conflict` (the PR stays open, its author resolves the module 9 conflict, and it is merged only after the D7 record is on `main`). See [pr43-codex-decisions.md](pr43-codex-decisions.md).
