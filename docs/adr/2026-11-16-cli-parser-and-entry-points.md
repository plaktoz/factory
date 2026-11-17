---
scope: repo
repo: factory
topic: cli-parser-and-entry-points
status: accepted
supersedes: []
---

# CLI parser and entry points for module 16

## Decision

Parse the CLI with `argparse` from the standard library, and install two entry points. `python -m factory_engine` is the repo engine's CLI and runs every command about a run. The `factory` console script, installed by `factory-launcher`, is the machine launcher: it handles the machine commands itself and hands every other command to the right engine.

Chosen option: `argparse-two-entry-points`.

## Context

[Module 16](../design/modules/16-drivers.md) lists about 25 commands, and [section 18](../design/shared/18-shared-contracts.md) says the launcher hands every command about a run to that run's own engine, `python -m factory_engine` from the run's kit snapshot. Neither file names a parser library or says how the `factory` command is installed. Other work depends on both: the dashboard already calls `factory <command> ... --json` as a subprocess (`factory/launcher/factory_launcher/server/launcher.py`), and the shipped skills call the CLI.

The engine's only runtime dependencies today are `PyYAML` and `jsonschema`, and the floor is Python 3.10 (module 3, decision G9). The kit is copied into other repos, so each dependency is one more thing a snapshot must carry.

## Options considered

- **`argparse-two-entry-points`** (chosen) (recommended): `argparse` for parsing; `python -m factory_engine` for the engine; a `factory` console script in `factory-launcher` for the launcher.
  - For: No new dependency, so a kit snapshot needs nothing more than it carries today
  - For: Subcommands, `--json`, repeated `--question`, and `D1=opt-a` positionals are all plain `argparse`
  - For: The dashboard's existing subprocess call (`factory <command> --json`) works as written
  - Against: More lines per command than a decorator library
  - Against: Help text and error messages are `argparse`'s own, so exit code 2 on misuse has to be checked, not assumed (`argparse` exits 2 on a usage error, which matches the shared "invalid input" code)
- **`click-or-typer`**: Add `click` or `typer` to the engine's dependencies.
  - For: Shorter command definitions and better help output
  - Against: A new runtime dependency in every kit snapshot, for a gain in style only
  - Against: Both libraries print their own error text and may choose their own exit codes, which must be forced to match the shared codes
- **`one-entry-point`**: Make `python -m factory_engine` the only entry point and have the dashboard call it with the interpreter path.
  - For: One entry point to install and test
  - Against: Breaks section 18's split, because the machine commands (`tick`, `dashboard`, `inbox`, `schedule`, `doctor`) must work without choosing an engine version
  - Against: The dashboard would need to know where each engine lives

## Why

`argparse` adds no dependency and matches the contracts already written, and two entry points follow the split that section 18 already states.
## Source

Written on 2026-11-16 by the session building module 16, under the AGENTS.md rule that a library or interface choice needs an ADR before work builds on it. The owner accepted `argparse-two-entry-points` in the session on 2026-11-16.
