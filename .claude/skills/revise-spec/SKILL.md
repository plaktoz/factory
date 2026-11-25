---
name: revise-spec
description: Score a design doc in docs/design/ or a proposed ADR on judgment dimensions and write an advisory scorecard. Use before you mark a change to either done, or when asked to review or score a spec. Advice only; it is not a gate or an approval.
---

# revise-spec

Score what the repo's scripts cannot see. The scripts check form (links, names, ticks). You check substance: can a builder build from this file, and does its reasoning hold? Write one scorecard. Never edit the file you score.

This is not `factory/skills/own/review-spec`. That skill is a workflow stage that checks a code change against a request. This one scores a document.

## Scope

- **Design doc:** any file under `docs/design/`. Use the four design dimensions.
- **Proposed ADR:** a file in `docs/adr/` whose front matter says `status: proposed`. Use the three ADR dimensions.
- **Not scored:** an `accepted` or `superseded` ADR (it cannot be edited; the only fix is a new ADR), and `docs/research/`. Say so and stop. For calibration only, `references/` scores accepted ADRs as examples.

## Steps

1. **Run the checks.** `python3 -I .claude/skills/revise-spec/scripts/precheck.py <file>` from the repo root. If it exits 1, print its output, write no scorecard, and stop. If it exits 0, copy its notes into the scorecard; they are problems elsewhere in the repo and do not block. Never score or mention a link, a signature, a tick count or a decision record yourself: the scripts settle those.
2. **Read the file whole, then the files it depends on.** For a module file, read its "Depends on" modules' contracts and the dependency map in `docs/design/shared/20-dependencies-and-plan.md`. Use the glossary in `docs/design/phase-1.md` section 2 for terms.
3. **Score each dimension 1 to 5, whole numbers.** Use the anchors below. Cite evidence as the rules below require.
4. **Set the recommendation by the lowest score:** `ready` if every dimension is 4 or more; `needs-changes` if the lowest is 3; `rework` if the lowest is 2 or less. There are no weights and no overall number. If two or more dimensions tie at the lowest score, name every tied dimension in the recommendation; the recommendation itself does not change.
5. **List blocking items:** one per dimension scored 3 or less, each naming the dimension and the line to change.
6. **Write the scorecard** to the screen, or to the file the user names.

## Keeping scores steady

- A score of 4 or 5 needs a **quoted line** with its line number that shows the property. No quote, no 4.
- A score of 3 or less needs the **specific missing item** named, with the line where it should be.
- When the evidence is thin or you are unsure between two scores, give the lower one.
- A score with no evidence line is invalid. Redo it.

## Anchors

| Score | Meaning |
| --- | --- |
| 5 | A builder or deciding person needs nothing else. The property holds in every case you tried, and the file says so in its own words. |
| 4 | Sound, with a minor gap that a careful reader can fill without asking. |
| 3 | The core works, but a key part is thin or missing. A builder would have to guess or ask. |
| 2 | Significant ambiguity or a missing part a builder cannot work around. |
| 1 | An outline or placeholder. |

## Design doc dimensions

1. **Scope and meaning.** A builder can tell what is in and what is out. Non-goals or boundaries are stated. Terms match the glossary and are used one way.
2. **Soundness.** The design holds together: it does not contradict itself or another file, its edge cases are named, and it fits the dependency map. A design doc is a contract, not a decision record, so it is not scored on rejected options; those belong to the ADR dimensions.
3. **Failure and safety behavior.** The file says what happens on a crash, bad input, a timeout, a missing dependency, or a sandbox or token problem, in this file and not only "fails fast". Rollout and rollback do not apply to a local tool; do not ask for them.
4. **Buildability and testability.** A builder with only the fakes of the upstream modules could finish it. Each acceptance criterion is observable and could fail. "Works correctly" does not count. Inputs, outputs and the fields of every type the file introduces are given. Checking a signature against the code is the script's job; whether a builder can code from the file is yours.

## Proposed ADR dimensions

1. **Options are real.** At least two options a reasonable person could pick, each stated fairly, with the cost of each.
2. **Recommendation is justified.** The reasons follow from the context and cite evidence: a file, a measurement, an earlier ADR.
3. **Consequences are stated.** What gets harder, what later work is now committed to, and what `supersedes` points at. A cost listed under the chosen option counts only if Consequences repeats it or points to it (owner decision, 2026-11-25, decision page item 28).

A **backfilled** record says it was written later from an earlier source. Score it on its own text. A source the reader cannot open in this repo is not evidence: write "unverifiable" in the evidence column and give it no credit. Do not lower a score only because a cited source is missing from this repo.

## Scorecard format

```
### Spec Scorecard: <file>
Mechanical checks: pass   (notes: <any note from precheck, or "none">)
Recommendation: <ready | needs-changes | rework>   (lowest: <dimension> = <score>)

| Dimension | Score | Evidence (line) | Key takeaway |
| --- | --- | --- | --- |
| ... | n | L<line> "<quote>" or missing: <item> | <one line> |

Blocking items:
- [ ] <Dimension>: <what to change> (L<line>)
```

## When an agent runs this

Run it before you mark a change to `docs/design/**` or a proposed ADR done. If the result is `needs-changes` or `rework`, fix the blocking items and run once more. If the second result is not `ready`, stop and report the scorecard to the person. Do not loop. Calibrated examples are in `references/`.
