# P2-9 finding: a trial eval of the `review-standards` reviewer

Run on 2026-11-15 with Claude Code 2.1.325, through the factory's own `ClaudeAdapter` and the real `no-blocking-findings` gate. The runner and cases are in `scripts/evals/reviewers/`. Results stay local and are not committed.

## Decision

**Build a thin factory runner. Do not build a scheduled suite yet.**

- The trial found two defects in the reviewer stage that no gate or fake could see. Evals earned their cost on the first day. Both defects are about wiring, not about model quality.
- Once the wiring is right, the reviewer scored 18 of 18 on recall and 0 false alarms. These cases are too easy to tell a good reviewer from a bad one. They show that the wiring works. They do not yet show that the reviewer is good.
- A scheduled regression suite is worth its cost only with harder cases. Those come from real misses in pilot runs ([P2-4](../design/phase-2.md#p2-4-pilot-repo-plaktoztest-adapters)), and none exist yet.

## What was run

One small Python repo (`ledger`) with seven written standards in `AGENTS.md`. Twelve cases, each a change left uncommitted in a git worktree.

| Kind | Cases | Grader |
| --- | --- | --- |
| Planted defect | 6, one standard broken each: float money, swallowed error, `print` in library code, hard-coded token, SQL built with an f-string, new function with no test | A finding names the planted file within 3 lines of the planted line |
| Clean | 6, four follow every standard, two are decoys (`print` in a test, a `LIMIT ?` change that is still parameterized) | No finding of medium or high severity |

Each case ran 3 times in two arms, 72 runs in all. The grader is code. No model judged anything. Both arms gave the reviewer the list of changed files as an operator note. The engine does not do that today (see defect 3).

- **`engine` arm.** The prompt exactly as `build_prompt` builds it.
- **`told` arm.** The same prompt plus the absolute artifact path and the five finding field names.

## Result

| | `engine` arm | `told` arm |
| --- | --- | --- |
| Artifact at the path the engine reads | 16 of 36 | 36 of 36 |
| Artifact at a guessed path, one folder up | 12 of 36 | 0 |
| No artifact anywhere | 8 of 36 | 0 |
| Passes the `review-findings` schema | 0 of 36 | 36 of 36 |
| Planted defect cited, by file and line | 16 of 18 | 18 of 18 |
| Clean runs with a blocking finding | 0 of 18 | 0 of 18 |
| Gate result is `gate.blocking_findings` on a planted case | 0 of 18 | 18 of 18 |
| Cost reported by the harness, 36 runs | $5.72 | $4.20 |
| Median run time, median turns | 29 s, 12 | 19 s, 8 |

The 2 planted runs the `engine` arm missed (`p4-hardcoded-token`, runs 1 and 3) wrote no artifact anywhere, so they are wiring losses and not a missed defect.

Cost is the sum of `total_cost_usd` in each run's result. The runs went through a gateway and the model name was `claude-advantage-assist`, so treat the dollar figure as the harness's own number and not as a price. Token counts are in `usage.jsonl` form (`input_tokens` 502 and 348, `output_tokens` 113k and 65k over 36 runs).

## Defects the trial found

These are not model failures. Each would hit a real run.

1. **The worker is told a path it cannot expand.** The prompt says `$FACTORY_TASK_DIR/standards.json`. A reviewer has Read, Write and Edit but no Bash, so it cannot read the variable. In the `engine` arm 20 of 36 runs wrote the file somewhere else. The engine reads back only `work/`, so it would find no artifact and fail the stage. Fix by putting the resolved absolute path in the prompt.
2. **The prompt does not give the artifact's fields.** It names the schema `review-findings` and nothing more, and the spec gives no fields. The schema forbids extra keys on a finding, and each of the 28 artifacts the reviewers wrote broke it. Findings carried `summary` (13 findings), `message` (6, allowed), `suggestion` (3), `evidence` (2) and `failure_scenario` (1), and the files added top-level keys such as `stage`, `task` and `verdict`. The gate returned `gate.schema` for every one. Fix by stating the fields in the prompt, once the owner has settled the schema. The trial reads the finding's own `file`, `line` and `severity`, so recall was still graded.
3. **The reviewer has no diff.** The prompt lists no changed files and the worker has no Bash. Several reviewers said so in their answer. Both arms got a changed-file list from an operator note, which the engine does not send. Real recall is probably lower than the table.

The gate behaved correctly throughout. It did not turn a schema failure into a pass.

## What this says about the open questions

- **Case.** A fixture repo, a request and a change, graded by code. This worked and needed no LLM judge.
- **Graders.** Code was enough for the reviewer. An LLM judge is not needed for a recall and false-alarm score.
- **Tool.** `claude plugin eval` does not fit. It has no code graders (only `regex`, `file_exists`, `tool_used`, `llm` and `baseline`). It starts each run in an empty folder, loads no `.claude/` or `CLAUDE.md`, and cannot run the factory's skills under the factory's sandbox. A runner that calls the real adapter was about 150 lines, kept the sandbox, and would work for a Codex adapter ([P2-1](../design/phase-2.md#p2-1-codex-worker-adapter)) with no change.
- **Cost.** About $0.12 to $0.16 and 20 to 30 seconds per reviewer run, as the harness reports it. A 12-case suite at 3 runs is about $4 to $6.
- **Storage.** Results are written under `scripts/evals/reviewers/results/`, which `.gitignore` excludes. They can hold private prompts. Nothing was published.
- **Safety.** No `eval()` anywhere. The runner uses argument lists, and the workers ran under the module 9 sandbox with the factory home set to a throwaway folder.

## Limits of this trial

- One model, reached through a gateway. A drift check needs at least two models.
- Six defect types, each obvious and in one file. A ceiling of 18 of 18 means the cases cannot rank reviewers.
- Three runs per case. A rate of 18 of 18 supports "usually", not "always".
- One clean case (`c6`) was wrong on the first pass. It changed a function that had no test, and the reviewer correctly flagged the missing test. I fixed the fixture and re-ran both arms. A hand-built clean case needs a check from a second person.

## Next steps

- [ ] Fix defects 1 and 2 in the module 9 prompt template. Add a fake-adapter test that fails when the prompt names `$FACTORY_TASK_DIR` for a worker with no Bash. That is a deterministic check, so it belongs to [P2-11](../design/phase-2.md#p2-11-review-the-architecture-for-more-deterministic-layers).
- [ ] The owner settles the `review-findings` fields (the schema is a draft).
- [ ] Decide how a reviewer sees the change (defect 3), then re-run the `engine` arm.
- [ ] After the pilot runs, add every real reviewer miss as a case. Then decide on a scheduled run and its budget cap.
