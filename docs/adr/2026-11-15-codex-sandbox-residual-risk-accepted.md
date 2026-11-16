---
scope: repo
repo: factory
topic: codex-sandbox-residual-risk-accepted
status: accepted
supersedes: []
---

# Sandbox promise for Codex workers under D7

## Decision

Accept both for Codex workers only, and record them in D7 as residual risk

Chosen option: `accept-both-codex-only`.

## Context

Checked on this machine with srt 0.0.83 and codex-cli 0.164.0: Codex with -s workspace-write fails inside srt (sandbox-exec: sandbox_apply: Operation not permitted), so the adapter uses -s danger-full-access and srt is the only layer. Codex also needs allowMachLookup com.apple.trustd.agent: without it a Codex run through srt timed out (exit 124), with it the run replied ok (exit 0). srt's README says that grant opens a potential data exfiltration route through trustd. The grant is in the Codex settings only; main has none.

## Options considered

- **`accept-both-codex-only`** (chosen) (recommended): Accept both for Codex workers only, and record them in D7 as residual risk
  - For: Both changes are verified to be needed, not optional
  - For: Claude workers keep the stricter settings; main has no trustd grant
  - For: The risk is written down in D7 where the owner can see it
  - For: Reversible: rejecting later only removes the Codex adapter
  - Against: Codex runs get weaker isolation than Claude runs: one OS layer, and a Mach route srt itself warns about
  - Against: The exfiltration route is documented by srt but not tested here
  - Against: D7 now has two isolation levels to keep straight
- **`reject-keep-codex-out`**: Reject both: Codex workers are not allowed in phase 1 or 2 until a stronger sandbox exists
  - For: D7 stays exactly as decided: one sandbox level for every worker
  - For: No new exfiltration route
  - Against: P2-1 stays incomplete and Codex cannot be used
  - Against: Throws away verified work and live smoke runs
  - Against: No stronger sandbox is planned, so this may be permanent
- **`accept-sandbox-only-probe-trustd`**: Accept the disabled Codex sandbox, but hold the trustd grant until a probe shows what can leave through it
  - For: Keeps the unverified route closed until it is measured
  - For: Gives a test to cite in D7
  - Against: Without the grant Codex cannot reach the gateway on macOS, so this is the same as rejecting Codex for now
  - Against: The probe is new work with no spec behind it
  - Against: Linux behavior is a separate unknown

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

Both changes were shown to be required, they apply to Codex only, and writing the residual risk into D7 keeps the decision visible and reversible.

## Source

Backfilled on 2026-11-16 from `docs/reviews/pr43-codex-decisions.md`, decision `D1`, page `docs/reviews/pr43-codex-decisions.json`. The owner chose this on 2026-11-15; the answer is the record's, not new.
