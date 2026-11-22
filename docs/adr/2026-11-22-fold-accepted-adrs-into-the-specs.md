---
scope: repo
repo: factory
topic: fold-accepted-adrs-into-the-specs
status: accepted
supersedes:
  - 2026-11-21-revise-spec-decisions-are-recorded-as-accepted-adrs
---

# An accepted ADR is folded into the spec and its file is deleted

## Decision

Accepted by the owner on 2026-11-22, in the session, with the words "accept the fold", after a proposal to move accepted ADRs into the module specs.

What now holds:

1. **An ADR is a pending question.** `docs/adr/` holds only `proposed` ADRs. The commit that accepts an ADR also folds its rule into the spec and deletes the file. Git keeps the full text.
2. **The spec says what is true now.** Each module file in `docs/design/modules/` ends with a `Decisions` table: Rule, Why, Not chosen, Id. A rule for a shared contract goes in `docs/design/shared/`, a phase 2 rule in `docs/design/phase-2.md`, and a rule about how this repo is built in `docs/process.md`.
3. **A `Decisions` row changes only through a new `proposed` ADR.** This keeps the lock that D1 to D14 and accepted ADRs had. The ADR that changes a row folds into it the same way.
4. **A one-off action or a calibration round is not folded.** Its file is deleted and git keeps it.
5. **The fold sha.** `docs/adr/README.md` names the commit that deleted the first batch. To read a folded ADR, run `git show <fold sha>:docs/adr/<id>.md`. This is the way `docs/README.md` already points to the retired `docs/reviews/` folder.

## Context

- 95 ADRs, about 250 KB and 38,000 words, sat in one flat folder with no index. 37 were written on 2026-11-21 alone. A file that is accepted and never edited cannot be kept up to date, so it only grows.
- 79 of the 95 changed a spec in their own commit, and 13 spec files link to an ADR for the reason behind a rule. Most rules are already in the specs. What was missing is the one-line why and the rejected option.
- `supersedes` held 2 entries across all files, so no ADR had a real chain of replacements.
- `2026-11-21-tell-the-worker-not-to-run-the-tests.md` has been 0 bytes since commit `ac3c9f5`. A check that only tests that an ADR file exists passes on it.

## Options considered

- **Fold accepted ADRs into the specs and delete the files** (chosen, recommended).
  - For: the folder stays near empty. An agent reads one module file, not 95 ADRs. The spec is the one place that is true now.
  - Against: the long options text leaves the working tree, one `git show` away. This breaks the rule against editing another author's ADR, and the lock on D1 to D14, so it needed the owner's yes.
- **Keep the folder flat and add an index grouped by component** (not chosen). The index lists 95 files and the folder keeps growing, so the same context problem comes back.
- **Move the ADRs into component folders** (not chosen). It breaks 10 links between ADRs that cannot be edited, changes 77 outside references, and forces one component on an ADR that spans several.

## Consequences

- `AGENTS.md`, `docs/README.md`, `records.py`, and the `decision-page` and `revise-spec` skills change in the same work. `records.py` stops requiring `tasks.md` to name every ADR.
- Reading a rule's history costs one `git show`.
- A session that finds an accepted ADR in `docs/adr/` folds it.
