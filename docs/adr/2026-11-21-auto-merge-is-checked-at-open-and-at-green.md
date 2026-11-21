---
scope: repo
repo: factory
topic: auto-merge-is-checked-at-open-and-at-green
status: accepted
supersedes: []
---

# Auto-merge is checked when the pull request opens, and again at the first green

## Decision

Accepted by the owner on 2026-11-21, on page `.scratch/open-items.json`, decision `D1`: option `open-then-green`. The page calls it "Check at open, again at green".

The engine checks the merge rules (`evaluate_merge`) twice for each pull request it opens:

1. **At open**, before the pull request is created, with CI `pending`. The verdict and its reason are in the pull request body's Merge line from the start. The engine asks for a review at the same time.
2. **At the first green read.** When `tick` reads the pull request and its checks are green, and the rules have not yet been checked with green CI, it starts an engine. The engine checks the rules again with CI `green`, and posts the verdict as a comment on the pull request: "Merge check with CI green: <verdict>". The body keeps the verdict it opened with, because nothing edits a pull request body after it is created. Only this check can allow auto-merge. If every rule passes, the engine asks GitHub to squash-merge with `--auto`. A later green read changes nothing.

A merge that branch protection refuses is logged as a `merge_blocked` event, and the run keeps waiting for a person at its merge review.

**Who is asked to review.** The person working on the request. The owner answered this in the session on 2026-11-21: "D1 reviewers will be the person working on the issue." For a GitHub request that is the issue's author, which the tracker already records as a GitHub login. A CLI or markdown request has no GitHub login, so nobody is asked, and the merge-review attention item under Needs you is the only signal. No configuration key is added.

This builds the part that ADR `2026-11-20-run-state-while-the-pull-request-is-open` lists under "Not built": `evaluate_merge` and `merge_or_request_review` had no caller on a live run. That ADR is otherwise unchanged and still holds.

## Context

Checked on 2026-11-21:

- A search of the engine found no caller of `evaluate_merge` or `merge_or_request_review` outside tests. A pull request the factory opened said "Not evaluated." on its Merge line (`summary._merge` with no `merge.json`, run) and asked nobody to review.
- A repo with no checks reads as `pending`, never `green`: `ci_from_rollup([])` returns `("pending", "no checks reported")` (run).
- The starter merge policy in `.factory/config/merge-policy.yaml` has `auto.workflows: []`, so every pull request goes to a person until the owner adds a workflow. Read from `STARTER_MERGE_POLICY` in `kit.py`.
- GitHub's "Allow auto-merge" setting is off on `plaktoz/factory` (`gh api repos/plaktoz/factory`, `allow_auto_merge: false`). A repo needs it on before `gh pr merge --auto` can work.
- `gh issue list --json author,assignees` returns the author's login. The assignee lists of the issues read were empty, so the author is the field that is always there.

## Options considered

- **`open-then-green`** (recommended, chosen): check at open, and again at the first green.
  - For: a person is asked to review at once, even in a repo with no checks.
  - For: the pull request says why it needs a person, in place of "Not evaluated."
  - For: matches module 13: auto-merge for opted-in workflows, human review for the rest.
  - Against: the first verdict always lists "CI is pending" among its reasons, which is noise.
  - Against: the verdict is written twice. The pull request body keeps the first one, and the second arrives as a comment, so a reader has to look in two places.
  - Against: a repo with no checks never auto-merges, because its checks never turn green.
- **`green-only`**: check only at the first green read.
  - For: one verdict, written once, with no "CI is pending" noise; the smallest change.
  - Against: a repo with no checks never gets a verdict or a review request.
  - Against: nobody is asked to review while the checks run, so a slow pipeline delays a person.
- **`human-only-1a`**: no auto-merge in phase 1a.
  - For: fits the pilot already agreed (one chore or bug-fix, merged by a person); nothing new to test against a real GitHub.
  - Against: changes what the phase 1a spec promises, so it needs its own record.
  - Against: the merge rules, `merge.json` and the review request stay built but unused, and nobody gets a written reason.

For the reviewer, a `reviewers` key in `factory.yaml` was considered and not used. The repo config schema is closed (`additionalProperties: false`), so it would need a schema change, and the owner's answer names a person the run already knows.

## Why

Asking for a review at open costs one call and gives a person the reason at once. The re-check at green is the only point where auto-merge can say yes.

## Consequences

- `prs.py`, `gh.py` and `fake_prs.py`: the pull request contract gains `comment(pr, body)`, which runs `gh pr comment <n> --body <text>`; module 7's block lists it.
- `delivery.py`: `evaluate_merge` records the CI state in `merge.json` and in the `merge_evaluated` event. New `changed_since_base`, `reviewers_for` and `green_check_done`. `_sink_of` is now `sink_of`, because the engine reads it.
- `engine.py`: `_finish` checks the rules before the summary is rendered when it is about to open a pull request, and asks for a review once the pull request exists. `_merge_review` calls `_merge_at_green` on the first green read.
- `tick.py`: `_pr_changed` is true on the first green read too, so `tick` starts an engine for it.
- Module 13 (when the rules are checked, who is asked, the flow diagram, the Writes line, three new functions, one criterion) and module 6 (the tick table and the event catalogue, which gains `merge_blocked`).
- Tests: seven new tests in `factory/engine/tests/engine/test_merge_review.py`, one in `factory/engine/tests/tracker/test_gh.py`, and two in `factory/launcher/tests/test_tick.py`. The old tick test that expected a green pull request to start nothing is split into "pending starts nothing" and "green already checked starts nothing", because D1 changes what a first green read does.
- To let anything auto-merge, a repo owner still adds a workflow under `auto.workflows` in `merge-policy.yaml` and turns on "Allow auto-merge" in the repo's GitHub settings. Both stay off until then.
- Not checked: a real GitHub. The pull request reading and merging have run only against `FakePullRequests`. The review request through `gh pr edit --add-reviewer` and the comment through `gh pr comment` have not run against a real pull request.
- Task: item 20 in `docs/tasks.md`.

## Source

Written on 2026-11-21 by the session that built it, from the owner's pasted answer to page `.scratch/open-items.json`, decision `D1`, and the owner's answer on reviewers in the same session. The page is a working copy in `.scratch/` and is removed once its decisions are recorded, so the options above are copied from it.
