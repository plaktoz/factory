# 16. Module: drivers

Part of the [phase 1 design](../phase-1.md#module-map). Build wave: 4. Contracts and acceptance criteria are in this file; shared types are in [section 18](../shared/18-shared-contracts.md). Terms such as run, stage, task, attempt and rework are defined in the [glossary](../phase-1.md#2-glossary).

The CLI is the primary driver and the only path that changes state. The router skill is a chat front end that calls the CLI and never starts tasks.

| Command | Does |
| --- | --- |
| `factory init` | Creates `.factory/` with its `.gitignore`, a starter `config/` and the shim excludes |
| `factory upgrade <version>` | Replaces `factory/`, regenerates shims, validates config |
| `factory doctor [--as-scheduler]` | Checks git, gh, harness binaries, variables and auth, and runs the worker sandbox canary ([module 9](09-worker-adapters-and-governed-helpers.md)); optionally in a cron-like environment |
| `factory tick [--all-repos] [--env-file]` | One scheduled pass: sync, start and resume engines, reminders, housekeeping |
| `factory schedule install --every 10m` / `remove` | Adds or removes the OS scheduler entry for `tick` |
| `factory add "title" [--type] [--body] [--files]` | Creates a run from CLI text or files |
| `factory sync` / `factory watch [--every 10m]` | Reads issues and the inbox once / runs `tick` in a foreground loop |
| `factory run [<run> \| --all] [--detach]` | Starts an engine on runs that can proceed |
| `factory resume <run>` | Continues a run whose engine has died (lock free) |
| `factory recover <run> [--rebuild]` | Closes open attempts; `--rebuild` replays `events.jsonl` into `run.json` |
| `factory status [<run>]` | Runs and stages in this repo; --here inside a worktree shows that run. Related: factory where, factory logs \<task>, factory events |
| `factory inbox` | Attention items across all repos, with decision page paths |
| `factory open <run> [--stage <s>]` | Opens the decision page in the default browser |
| `factory decide <run> --packet <sha> D1=opt-a [--notes] [--question D1="..."]` | Answers a human stop; refused if the packet changed |
| `factory check <run>` / `factory reopen <run>` | Re-evaluates a decision file / unlocks an approved one |
| `factory note <run>/<task> "text" [--deny glob]` | Queues a note |
| `factory retry`, `goto`, `skip`, `abort <run>` | Blocked-run actions |
| `factory usage [<run>]` | Token totals per observed model |
| `factory gc [--apply]` | Shows, then applies, the housekeeping plan |
| `factory plugins enable\|disable <name>` | Manages plugins |
| `factory dashboard [--port 8765] [--detach]` | Starts the dashboard server |

Internal commands used by workflow stages: `factory intake normalize`, `factory triage`, `factory sink <kind>`.

**Router skill** (`/factory` in Claude Code)

- It maps phrases such as "run bug-fix on issue 42" to CLI commands and reports status.
- For a human stop, it shows the decision in the picker format and answers through `factory decide`.
- It never writes state files or starts workers. If the chat ends, the run continues, because the engine and the state belong to the CLI.
- Every acceptance test runs through the CLI, so the router skill adds no extra execution path.

**Module contract: 16 Drivers**

- **Depends on:** every module. Drivers are the only place modules are composed: the repo engine's `api.py` and `cli.py`, the machine launcher, `tick`, `schedule` and the router skill.
- **Writes:** OS scheduler entries, `~/.factory/logs/` and `~/.factory/tick.json`.
- **CLI it backs:** every command in the table above.

```python
# api.py (repo engine): one function per command, each composing modules
def add(repo, title, *, type=None, body=None, files=None) -> RunRef          # 4
def sync(repo) -> SyncReport                                                 # 4, 7
def run(repo, run_ids=None) -> EngineResult                                  # 6B with real adapters
def decide(repo, run_id, stage, *, packet_sha, choices=None, questions=None,
           notes="", by, channel) -> Outcome                                 # 11, then spawn_engine
def note(repo, run_id, task_id, text, *, deny=None) -> NoteRef               # 12
def retry(repo, run_id, *, stage=None, note=None) -> None                    # 8 counters, then spawn_engine
def goto(repo, run_id, stage) -> None; def skip(repo, run_id, gate, *, reason) -> None
def abort(repo, run_id, *, reason) -> None                                   # takes the lock briefly
def recover(repo, run_id, *, rebuild=False) -> None                          # 6A, 14
def usage(repo, run_id=None, since=None) -> UsageReport                      # 14
def gc(repo, *, apply=False) -> GcPlan                                       # 17
def spawn_engine(repo, run_id) -> int | None
    """Start `factory run <run_id> --detach` unless a live lock exists; return pid."""
# launcher (machine): dispatch and machine commands
def dispatch(argv: list[str]) -> int        # find repo by cwd, --repo, or the run's repo path; exec its engine
def tick(cfg: Config, *, repos: list[Path]) -> TickReport
    """cfg comes from load_config(None): the machine part only, with repo=None. For each repo in
    repos, tick calls load_config(repo) for the steps that read repo settings (sync, housekeeping)."""
def schedule_install(every: str, *, dashboard: bool = False) -> None
```

**Run commands in detail**

| Command | Parameters | Behavior | Exit codes |
| --- | --- | --- | --- |
| `factory run` | `[<run> ...] \| --all`, `--detach`, `--poll 5`, `--json` | Takes each run's lock and drives it until done, failed, aborted, blocked or waiting. `--detach` starts the engine in the background and returns its pid | 0, 1, 3, 4, 5 |
| `factory tick` | `--all-repos \| --repo <path>`, `--env-file <path>`, `--json` | The scheduled pass in [module 6](06-engine-core.md). Never runs a worker, and returns within seconds | 0, 1, 2 |
| `factory decide` | `<run> [--stage <s>] --packet <sha> D1=opt-a ... [--notes] [--question D1="..."] [--by] [--json]` | Records the answer, then starts an engine if none holds the lock | 0, 2 (stale packet or bad choice) |
| `factory add` | `"title" [--type] [--body file] [--files a.md b.md] [--repo]` | Creates the run and prints its id; starts an engine unless `--no-run` | 0, 2 |
| `factory sync` | `[--repo] [--json]` | Reads sources once and creates runs without starting engines | 0, 1 |

The launcher finds the repo from the current folder, `--repo`, or, for a run id, the repo path recorded in its run.json. So `factory decide <run>` works from any folder.

The **router skill** maps chat phrases to these same commands and shows decision packets in the picker format. It never writes state.

- **Run and test:** `pytest factory/engine/tests/api factory/launcher/tests`, plus an end-to-end test that runs the bug-fix workflow on a seeded repo with `FakeWorkerAdapter` and `FakePullRequests`, driven only through the CLI.
- **Errors:** CLI misuse exits with code 2. Every command supports `--json` with the shared error shape. The router skill shows CLI messages as they are.

Acceptance criteria:

- [ ] Every command documented above exists, supports `--json` and uses the shared exit codes.
- [ ] Two repos on different kit versions are driven by their own engine through one launcher.
- [ ] `decide`, `retry`, `goto` and `skip` start an engine only when no live lock exists.
- [ ] Two ticks fired together: the second exits at once and no run starts twice.
- [ ] `tick` takes the `Config` from `load_config(None)`, with no repo part, and reads each repo's own settings through `load_config(repo)`; no `MachineConfig` type exists.
- [ ] `tick` polls open pull requests, routes red CI back to fix, and finishes runs whose PR merged.
- [ ] `schedule install` writes a working entry on Linux and macOS (launchd, cron or a systemd timer); `remove` deletes it. Windows is phase 2.
- [ ] `init --github` composes `init_repo` (3) with `ensure_labels` (7).
