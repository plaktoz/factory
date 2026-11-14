# Wave 0 report

Date: 2026-11-14. Scope: W0.1 to W0.7 in [the task list](../tasks.md). Each item below names the test that backs it. "Checked" means the test ran on Python 3.10 and 3.15 with the result shown.

## Counts (measured)

| Suite | Tests | Result |
| --- | --- | --- |
| Engine (`factory/engine/tests`) | 75 | all pass, 3.10 and 3.15 |
| Spec contracts (`scripts/docs-check/spec-contracts`) | 77 | all pass, 3.10 and 3.15 |
| Docs checks | 181 links, 0 broken; diagrams parse | `scripts/docs-check/links.py`, `mermaid.mjs` |

## Items

| Item | What it delivers | Backed by |
| --- | --- | --- |
| W0.1 package skeleton | `pyproject.toml` (Python >=3.10), package, smoke test | `tests/test_package.py` (2) |
| W0.2 `errors.py` | `FactoryError` takes kind and hint from the catalogue; five kinds; exit codes; one code per sandbox failure type | `tests/shared/test_errors.py` (10) |
| W0.3 `types.py` | Section 18 shared types, plus `Workflow`, `Stage`, `TaskSpec`, `Policy`, `Defaults`; `Config` in `config.py` | `test_types_match_spec.py` (28 field-list checks, one per spec dataclass; all 28 spec dataclasses exist in code) |
| W0.4 schemas | 12 JSON Schemas in `factory/schemas/`; 5 generated from the dataclasses | `tests/shared/test_schemas.py` (43) and `test_spec_examples_validate.py` (every spec example for a state or config file validates) |
| W0.5 fakes | `FakeClock`, `FakeWorkerAdapter`, `FakeTracker`, `FakePullRequests` | `tests/fakes/test_fakes.py` (20): success, failure, timeout, cursor, CI, auto-merge |
| W0.6 contracts | Every spec signature parsed (146); built signatures and the four fakes checked | `test_signatures_match_spec.py` (77 in total across the spec-contract suite) |
| W0.7 report | This file | — |

## Section 18 acceptance points

Section 18 has no acceptance list of its own. These are the points the wave 0 procedure requires ("the shared types, the schemas, the error and exit codes, and the four fakes exist, and the contract tests pass"), each with its test.

| Point | Status | Test |
| --- | --- | --- |
| The shared types exist as written | Done: all 28 spec dataclasses and every name in section 18's code blocks (31) | `test_types_match_spec.py`, and a one-off check of section 18 names |
| The schemas exist for the files module 3 lists | **Partly done:** 12 of 17. The other 5 have no fields in the spec (`merge`, `stage-report`, `test-report`, `source-notes`, `review-findings`) | `test_schemas.py`; module 3 lists the owning module for each |
| Error codes and exit codes | Done: 11 codes in the catalogue, exit codes as section 18 | `test_errors.py` |
| The four fakes exist | Done | `tests/fakes/test_fakes.py` |
| The contract tests pass | Done for the 14 built signatures and 16 fake checks; 132 signatures are pending | `test_signatures_match_spec.py` |

## What is left for wave 1

1. **The 132 pending signatures**, in 27 files (the largest: `state.py` 23, `api.py` 16, `gitops.py` 13, `decisions.py` 7). These come with their modules. The count may only go down.
2. **The 5 schemas with no fields in the spec.** Module 13 defines `merge`; modules 5 and 10 define `stage-report`, `test-report`, `source-notes` and `review-findings`. Each is written in its own wave, from its own spec text, or the spec is changed first.
3. **`SkillRef`** is a stand-in in `adapters/worker/base.py`. Module 10 defines it in wave 1, and the stand-in is removed then.
4. **Real adapters.** Only the fakes exist. `ClaudeAdapter` (module 9), `FileTracker` and `GitHubTracker` (module 7), and `GitHubPullRequests` are wave 1 to 2 work.
5. **The error catalogue grows** with each module (G3). Module 8's `classify` and module 16's `--json` need rows the catalogue does not yet have.

## What is not claimed

- No test has exercised any real CLI, git repository, GitHub call or Claude run. Wave 0 is types, schemas and fakes only.
- Python 3.10 and 3.15 are the two versions run. Other versions are not checked.
- The sandbox behaviour (the `sandbox.*` codes) is recorded from the 2026-11-14 tests. It is not re-run in wave 0.

## Decisions taken during wave 0 (not in the spec before)

- YAML is read with YAML 1.2 booleans (module 3 now says so).
- The spec-reading tests live in `scripts/docs-check/` so `factory/` never references `docs/` (AGENTS.md).
- Commits use the local identity `tianhong`, with no email, from this point.
