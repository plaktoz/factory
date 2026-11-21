---
scope: repo
repo: factory
topic: revise-spec-runs-the-checks-first
status: accepted
supersedes: []
---

# revise-spec runs the existing checks first and scores only what they cannot see

## Decision

Accepted by the owner on 2026-11-21, on page `.scratch/issue-55-revise-spec.json`, decision `D1`: option `checks-first-hard-stop`, the recommended option. The page called it "Run the checks first, stop if any fail".

Before it scores a file, the `revise-spec` skill runs `.claude/skills/revise-spec/scripts/precheck.py <file>`. That script reads the output of `links.py`, `contracts.py`, `criteria.py` and `records.py`. If any of them reports a problem **about the file being scored**, the skill prints the problems, writes no scorecard and stops. A problem elsewhere in the repo is printed as a note and does not block. The skill never scores a link, a name, a tick count or a decision record itself.

The stop is narrower than the page's wording. The page said "stop if any fail". Run against this repo that would have blocked every file, because `records.py` fails today on `docs/tasks.md` (see Context). The rule that holds is: stop on a failure about this file.

## Context

Checked by running the scripts on 2026-11-21:

- `links.py` and `contracts.py` exit 0 even when they print problems (`links.py` printed `211 links; 1 broken` and exit 0 on a planted bad link), so an exit code cannot be the stop.
- `criteria.py` exits 1 for any open criterion, including one marked `(not ticked: reason)`, which `AGENTS.md` allows. Module 5 would be blocked only for honest phase 1b work.
- `records.py` printed `` `main` is at e147fa1, 4 merges behind origin/main (max 3) `` on this branch before any change here. That problem is about `docs/tasks.md`, not about any spec being scored.
- The first version of the wrapper missed a planted broken link, because `links.py` indents its lines by two spaces. It was fixed, then a broken link, an unknown upstream name and a tick with no test path were each planted and each blocked.

## Options considered

- **`checks-first-hard-stop` (chosen, recommended).** Run the checks, stop on a failure about the file.
  - For: nothing is scored twice, so a link error cannot lower a quality score. Scores describe only a mechanically sound file. The issue's tracking-issue and rollback checks are dropped.
  - Against: one stale link blocks quality feedback until it is fixed. It depends on the five checks staying readable by the wrapper.
- **`checks-first-warn-continue` (not chosen).** Run the checks, print failures, score anyway.
  - For: feedback arrives even with a broken link.
  - Against: a broken link can leak into a quality score, and a `ready` can sit beside a failed check.
- **`independent` (not chosen).** The skill never looks at the checks.
  - For: the simplest skill, and it works where the checks cannot run.
  - Against: a scorecard can approve a file with broken links, and the skill may re-judge what the checks settle.

## Why

Each fault is reported once, in the place built to report it. A narrow stop keeps that true without making the skill unusable while an unrelated record is stale.

## Consequences

- `precheck.py` reads the printed output of the four scripts. If one changes its output format, the wrapper must change with it. The wrapper's own faults were found only by planting them, so it needs a test (not built by this ADR; see the task).
- The wrapper treats `criteria.py` output as a fault only for "ticked without a test path" and "open without a reason".
- `mermaid.mjs` and `spec-contracts/` are not run by the wrapper. The first needs a Node install, and the second needs the engine's environment.

## Source

Written on 2026-11-21 by Claude Code from the owner's answer on `.scratch/issue-55-revise-spec.json`, decision `D1`. The page is removed once every decision on it has an ADR. The answer is the owner's, not new.
