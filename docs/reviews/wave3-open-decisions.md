# Wave 3 open decisions: triage notes

Page: `docs/reviews/wave3-open-decisions.html`. Data: `docs/reviews/wave3-open-decisions.json`. Earlier page for the same wave: [wave3-decisions.md](wave3-decisions.md) (D1 to D3, applied). PR #43 is on [pr43-codex-decisions.html](pr43-codex-decisions.html) and is not repeated.

## On the page

| Id | Decision | Recommended |
| --- | --- | --- |
| D1 | The owner's work email in commit `6a6ff04` | `keep-history-redact-text` |
| D2 | Dashboard in phase 1a: placeholder or React | `placeholder-for-1a` |

Steps that wait on an owner answer: the PR #43 merge (its page, D1 and D2 there); the tutorial's dashboard section and the module 15 UI tests (D2 here). Module 6B, module 16 and the integration tests wait on the `factory-40` session's 6B pull request, which is not an owner decision.

## Settled without the owner (decided at recommendation, reversible)

| Item | Check | Result |
| --- | --- | --- |
| `docs/adr` and `docs/research` in `delivery.py` | `grep -rn "docs/" factory`: 3 production hits, all in `delivery.py`; none names `docs/design`, `docs/reviews` or `docs/tasks` | They name target-repo folders (modules 7 and 13). One sentence added to `AGENTS.md` saying so. This closes the open question in [wave3-decisions.md](wave3-decisions.md). |
| 6B: workers supervised in threads | Read `engine.py` on `wave3/m06b-engine`; module 6 records it as "open to change by a new ADR" | Internal, reversible, invisible to the owner. Stays. |
| 6B: a failed gate resets the run branch to its pre-join commit | `engine.py` line 525 does `reset --hard <pre_join>`; module 7 already resets on a join conflict; module 8 step 3 says the run branch "keeps its commits" for rework | The module 8 sentence is about rework after a gate fails with the work in place. Reconcile the wording in the 6B pull request. Not an owner call. **Not checked:** no test names the reset in `test_engine.py`. |
| 6B: triage candidates are Unspecified | `TYPE_WORKFLOW` lists five workflows; only `_triage`, `bug-fix`, `chore` and `reviewer-eval` exist. `workflow._find("feature")` raises `config.invalid` | Fix in 6B or module 4: offer only workflows that load. Not an owner call. Task below. |
| Gradle, golangci-lint, dotnet, prettier, eslint untested | None on PATH; `test_toolchains.py` says a stub stands in | A report item. Phase 1a needs Python only; 17A's tests use stubs. Listed in `docs/tasks.md`. |
| Linux pre-pilot check | `podman` 6.1.4 runs a Linux arm64 machine here | A task, not a decision. Run `factory doctor` in it before the pilot. |
| `srt` tests skip | `pytest tests/workers/test_command_adapter.py`: 24 passed, none skipped (`srt` 0.0.83, Node 26.13.0 installed) | `tasks.md` item 7 said `srt` was missing; that was true of another machine. Corrected. |

## Not asked

- "Both 2 and 3" criteria (`design-phase-constraint.md`): the text is in no file; the owner would have to restate it. Not a choice.
- `scope` skill vs `tasks_from`, and `every-claim-has-source`: phase 1b tasks, already in [wave3-decisions.md](wave3-decisions.md).
- Phase 2 "Unspecified" items in `docs/design/phase-2.md`: out of scope until phase 1 closes.

## Tasks created

1. Module 4 or 6B: build the triage candidate list from workflows that load.
2. Reconcile module 8 step 3 with the 6B gate reset, and add a test that names it.
3. Run `factory doctor` in the Linux machine under `podman`.

## Facts checked for D1 and D2

- Public API returns the author email of `6a6ff04`: yes (`gh api repos/plaktoz/factory/commits/6a6ff04`).
- `git for-each-ref --contains 6a6ff04` over `refs/pull/*/head`: 44 of 45. Remote branches: 45. Commits on main: 77, 73 after `6a6ff04`. Forks: 0.
- GitHub's guide on removing sensitive data: pull request refs are read-only, and only GitHub Support clears them.
- `git-filter-repo` is not installed here.
- React source in the repo: none (`find` for `package.json`, `.jsx`, `.tsx`). Placeholder: 296 lines, no usage view.
