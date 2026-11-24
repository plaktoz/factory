---
scope: repo
repo: factory
topic: reviewer-request-skips-the-pr-author
status: proposed
supersedes: []
---

# When the issue author also opens the pull request, who should review it?

## Decision

Question for the owner: the engine asks the issue author to review each pull request (`factory/engine/factory_engine/delivery.py`, `reviewers_for`). GitHub silently drops a review request to the pull request's own author. So when the issue author also opens the pull request, nobody is asked. Which should happen?

Recommended option: **ask nobody when the author opens it.** The merge review remains the check that stops the run for a person. If the owner accepts, `reviewers_for` returns nothing when the author is the pull request author, and the verdict says so in the pull request body.

## Context

- Checked by running on a scratch repo (`plaktoz/factory-gc-scratch`, 2026-11-24): `gh pr edit --add-reviewer` for the PR's own author exits 0 and `requested_reviewers` reads back empty. The adapter reports success.
- Auto-merge is not affected: the factory asks GitHub to merge only when the merge rules pass, as before.
- Changing who is asked is a scope change, so it waits for the owner.

## Options considered

1. **Ask nobody when the author opens it (recommended).** For: nothing is asked that GitHub will drop; the merge review still stops for a person. Against: a self-filed issue gets no review request at all.
2. **Name a second reviewer in the config.** For: a real review is requested every time. Against: a new config key, which is a contract change; a named person per repo.

## Why

The request is silently dropped, so asking the author gives no signal. Option 1 uses the merge review that already exists. Option 2 adds a config contract that the owner has not asked for.

## Consequences

- If option 1 is accepted: `delivery.reviewers_for` returns an empty list when the author opens the pull request; a test covers it; the pull request body says that no review was requested.
- Not built by this ADR: option 2 (a config key).
- Supersedes: none.

## Source

Written 2026-11-24 from the decision page `open-stops-2026-11-24` (`.scratch/open-stops-2026-11-24.json`, decision `D2`), which is deleted once this ADR is recorded. The full card text is copied into this file, so the page is not needed to read it.
