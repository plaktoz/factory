# Proposed decisions

This folder holds only `proposed` ADRs: questions waiting for the owner. An accepted ADR is folded into a `Decisions` table in the spec it belongs to, and its file is deleted in the same commit. The rule is in [`AGENTS.md`](../../AGENTS.md) and [`process.md`](../process.md).

## Reading a folded ADR

The full text of a folded ADR is in git, in the commit that deleted it. To read one:

```sh
git show "$(git log --diff-filter=D --format=%H -1 -- docs/adr/<id>.md)^:docs/adr/<id>.md"
```

`<id>` is the file name without `.md`. The first fold, of the ADRs from 2026-11-14 to 2026-11-22, is the commit whose message starts "Fold accepted ADRs into the specs".

## Folded decisions and where they went

| Spec | Rows |
| --- | --- |
| `docs/design/modules/03-kit-and-configuration.md` | kit and configuration rules |
| `docs/design/modules/04-intake-and-triage.md` | triage reads its request from the task folder |
| `docs/design/modules/05-workflows-and-plugins.md` | workflow, report schema and plugin rules |
| `docs/design/modules/06-engine-core.md` | run lock, crash recovery, run state |
| `docs/design/modules/07-git-and-github-operations.md` | checkpoint commits, branches, worktree comparison |
| `docs/design/modules/08-gates-error-handling-and-rework.md` | gate and error rules |
| `docs/design/modules/09-worker-adapters-and-governed-helpers.md` | worker isolation and sandbox |
| `docs/design/modules/10-skills.md` | skill rules |
| `docs/design/modules/11-human-stops.md` | approvals on rework |
| `docs/design/modules/13-delivery.md` | auto-merge and review rules |
| `docs/design/modules/14-token-tracking.md` | token and usage rules |
| `docs/design/modules/15-dashboard.md` | dashboard rules |
| `docs/design/modules/16-drivers.md` | CLI and engine selection |
| `docs/design/modules/17-housekeeping.md` | gc and cleanup rules |
| `docs/design/shared/18-shared-contracts.md` | shared types and command lists |
| `docs/design/shared/20-dependencies-and-plan.md` | scope and pilot timing |
| `docs/design/phase-2.md` | Codex moves to phase 2 |
| `docs/process.md` | how this repo is built |

Each row keeps the ADR's id, so the table can be searched for an id.
