---
scope: repo
repo: factory
topic: decide-answers-are-positional-tokens
status: accepted
supersedes: []
---

# `factory decide` takes its answers as trailing `ID=option` tokens

## Decision

`factory decide <run> --packet <sha> D1=opt-a D2=opt-b` takes each answer as a trailing positional token, in any position among the options. The CLI reads the leftover tokens with `parse_known_args` and checks that each one matches `ID=option`. Any other token is a usage error, exit 2, code `cli.usage`. The `--choice` flag is removed.

Chosen option: `positional-per-spec`.

## Context

`factory decide` records a person's answer to a human stop. The CLI, the router skill and the dashboard's Submit button all call it, so its argument form is shared by three callers. The spec and module 11's example write the answers as trailing tokens. The build agent first built a repeatable `--choice D1=opt-a` instead, because it believed argparse cannot take a variable positional list between options.

Checked: with a plain positional list, argparse fails on Python 3.10.22 and 3.13.0 when the answers follow an option (`unrecognized arguments`), and `parse_intermixed_args` raises `TypeError` on 3.10 and 3.15. With `parse_known_args` and a check that every extra token looks like `ID=option`, the spec's form parses on 3.10.22 and 3.15.0 with the answers before, between or after the options. The dashboard (`launcher/server/app.py`, tested in `test_pages_and_writes.py`) already sent the positional form, and the `--choice` build rejected that argv with exit 2.

## Options considered

- **`positional-per-spec`** (chosen) (recommended): Build the spec's positional form with `parse_known_args`, and drop `--choice`.
  - For: Matches the spec, module 11's example, the dashboard and its tests, so nothing else changes
  - For: Fixes the dashboard Submit, which the `--choice` build rejected
  - For: One form to document and to teach in the router skill
  - For: Checked on 3.10.22 and 3.15.0: answers before, between or after `--notes`, `--question` and `--packet` all parse
  - Against: The CLI checks the extra tokens itself, so a typo such as `oops` is reported by our code with its own message, not by argparse
  - Against: [cli-parser-and-entry-points](2026-11-16-cli-parser-and-entry-points.md) says positionals are plain argparse. That holds only with this workaround, and that ADR stays as written because another author wrote it
  - Against: A small change to `cli.py` plus a test for each option order
- **`choice-flag-amend-spec`**: Keep `--choice D1=opt-a`, and change the spec, module 11, the router skill and the dashboard to match.
  - For: Plain argparse: help text lists the flag and argparse reports every usage error
  - For: No workaround code in the parser
  - For: The flag is explicit, so a decision id can never be mistaken for a run id
  - Against: Edits the spec, module 11's example, the router skill and `launcher/server/app.py` with its tests, which is more files than the chosen option
  - Against: Reverses a contract two finished modules (11, 15) already rely on
  - Against: The reason for it, that argparse cannot do the positional form, is not true on the versions checked
- **`both-forms`**: Accept both: the spec's positional tokens and `--choice` as an alias.
  - For: The dashboard and the spec work unchanged, and the build already written keeps working
  - For: Scripts that used `--choice` in the last day do not break
  - Against: Two ways to do one thing, both to document and to test
  - Against: A call that mixes both forms needs a rule for which wins
  - Against: No caller outside this branch uses `--choice` yet (nothing is pushed), so the alias protects nothing that exists

## Why

The page's reason is for the chosen option. The owner's own reason is not recorded.

The spec, module 11 and the dashboard already agree on the positional form, and it parses on both supported Pythons, so the least change is to meet the spec.

## Consequences

- `cli.py` parses `decide` with `parse_known_args`; `tests/drivers/test_cli.py` has a test for each option order, one for `--question`, and one for each stray token (`oops`, `--choice D1=opt-a`, a mistyped flag), all exit 2. A command other than `decide` still rejects a stray token.
- Commit `94962c7` built it. The stub in `test_cli.py` replaces `api.decide`, so those tests prove the parsing. The end-to-end test in `test_cli_end_to_end.py` is the one that shows the form works against a real decision file (see [cli-end-to-end-test-runs-bug-fix](2026-11-17-cli-end-to-end-test-runs-bug-fix.md)).

## Source

Answered on 2026-11-17 on page `docs/reviews/m16-cli-decisions.json`, decision `M1`. The owner chose `positional-per-spec`, the recommended option, and the session's brief names it ("the M1 form: positional `D1=opt-a` tokens, no `--choice`"). The owner then asked for this ADR to be written (2026-11-17). The owner has not yet read its text, so `accepted` here rests on that answer; the owner can supersede it with a new ADR.
