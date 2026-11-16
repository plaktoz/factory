---
scope: repo
repo: factory
topic: linux-and-oauth-testing
status: accepted
supersedes: []
---

# Linux and OAuth login: when to test

## Decision

OAuth login is out of scope (phase 1 uses a key or gateway token). Linux is a pre-pilot check: `doctor` must pass the canary on Linux before the phase 1a pilot.

## Context

Neither is tested. This machine is macOS with a gateway token. Linux needs bubblewrap, and Claude Code names it in the binary. An OAuth login needs a machine that has one. Both change whether D7 holds, and wave 0 does not need either.

## Options considered

- **`gate-at-1a-pilot`** (recommended): Test both before the phase 1a pilot run; the doctor canary fails on any machine where it does not pass
  - For: Wave 0 starts now
  - For: doctor already proves the boundary per machine, so an untested machine cannot silently run workers
  - For: The pilot is the first run on the owner's real setup
  - Against: Linux support is claimed in D6 but unproven until then
  - Against: A surprise could change the module 9 text late
- **`test-before-wave-0`**: Test both now, before wave 0
  - For: No claim goes into code unproven
  - Against: Blocks wave 0 on machines and logins this session does not have
  - Against: Wave 0 touches neither
- **`macos-only-1a`**: Declare phase 1a macOS only and move Linux to 1b
  - For: Claims only what was tested
  - Against: Reopens D6, which stands
  - Against: Needs your sign-off on a scope change

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

doctor makes an untested machine fail closed, so waiting costs nothing.

## Source

Backfilled on 2026-11-16 from `docs/reviews/open-decisions.md`, decision `Q5`, page `docs/reviews/open-items.json`. The owner chose this on 2026-11-14; the answer is the record's, not new.
