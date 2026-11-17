---
scope: repo
repo: factory
topic: dashboard-plain-page-in-phase-1a
status: accepted
supersedes: []
---

# Dashboard in phase 1a: placeholder page or React bundle

## Decision

Phase 1a ships the placeholder page, with a usage view added. The React bundle moves to phase 1b

Chosen option: `placeholder-for-1a`.

## Context

The spec says React, shipped as a prebuilt bundle. Module 15 merged with a 296-line plain HTML placeholder at factory/dashboard/index.html. It shows Needs you, the runs overview, run detail and Show JSON. It has no usage view, although the server returns usage in run detail. The repo holds no React source (no package.json, no .jsx or .tsx files). The module 15 criteria for the page (refresh, Needs you buttons, run detail paths) are unticked until a UI test runs. The tutorial's dashboard section depends on this.

## Options considered

- **`placeholder-for-1a`** (chosen) (recommended): Phase 1a ships the placeholder page, with a usage view added. The React bundle moves to phase 1b
  - For: The pilot needs a read-only page, and the placeholder already does that
  - For: Unblocks the tutorial and the UI tests now, with no new build chain
  - For: Spec change is small: one row in the phase split table and one criterion note
  - Against: The spec says React for the dashboard, so phase 1a ships something other than what the spec describes
  - Against: UI tests written for the placeholder markup need rewriting when React lands
  - Against: Visual design stays plain until 1b
- **`build-react-now`**: Build the React source and its bundle before phase 1a closes
  - For: Matches the spec as written; no spec change
  - For: UI tests are written once, against the real page
  - For: Node 26.13.0 is installed here, so a build is possible
  - Against: Starts from nothing: there is no React source in the repo
  - Against: Adds a build step and a bundle to the kit, and delays the tutorial
  - Against: Spends phase 1a time on UI polish, not on the engine path the pilot proves
- **`plain-page-for-good`**: Make the plain page the dashboard and drop React from the spec
  - For: No build step or Node needed to serve the dashboard
  - For: One page to test, with the UI tests written once
  - For: The spec and the code agree
  - Against: Reverses a decision in the phase 1 spec, so it needs a new ADR
  - Against: Phase 1b writes (Submit, notes, retry, goto, skip, abort) are harder to build as hand-written markup
  - Against: Gives up the designed UI the spec promises

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

The pilot is read-only and the engine path matters more; the placeholder covers it now and React can follow in 1b without redoing the server.

## Source

Backfilled on 2026-11-16 from `docs/reviews/wave3-open-decisions.md`, decision `D2`, page `docs/reviews/wave3-open-decisions.json`. The owner chose this on 2026-11-15; the answer is the record's, not new.
