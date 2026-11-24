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
| `factory schedule at --at <local time> --name <job> -- <command>` / `remove --name <job>` | Writes or deletes an OS entry that runs one command once, from the current folder. Like `install`, it only writes the file and prints the `launchctl bootstrap` or `systemctl --user enable --now` line; the user loads it. Once loaded it outlives the session that asked for it. The time is local, with no year, and must be in the future. The command's output goes to `~/.factory/logs/once-<name>.log`; a command that fails still removes the entry, and the entry exits with its code. A second `at` with the same name overwrites the file. A machine that is off at the time is untested. |
| `factory add "title" [--type] [--body] [--files]` | Creates a run from CLI text or files |
| `factory sync` / `factory watch [--every 10m]` | Reads issues and the inbox once / runs `tick` in a foreground loop |
| `factory run [<run> \| --all] [--detach]` | Starts an engine on runs that can proceed |
| `factory resume <run>` | Continues a run whose engine has died (lock free) |
| `factory recover <run> [--rebuild]` | Closes open attempts; `--rebuild` writes `run.json` from the last `run_snapshot` in `events.jsonl` (decision E1, [module 6](06-engine-core.md)) |
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
def doctor(repo, *, as_scheduler=False) -> list[CheckResult]                    # 3, then 9 srt, sandbox canary, Claude check, canary and isolation probe, then 10 lock and pack size, then 17A toolchains
def spawn_engine(repo, run_id) -> int | None
    """Start `factory run <run_id> --detach` unless a live lock exists; return pid."""
# launcher (machine): dispatch and machine commands
def dispatch(argv: list[str]) -> int        # find repo by cwd, --repo, or the run's repo path; exec its engine
def tick(cfg: Config, *, repos: list[Path]) -> TickReport
    """cfg comes from load_config(None): the machine part only, with repo=None. For each repo in
    repos, tick calls load_config(repo) for the steps that read repo settings (sync, reminders, housekeeping).
    TickReport.reminded lists the runs it sent a reminder for."""
def schedule_install(every: str, *, dashboard: bool = False) -> None
def install_once(name: str, at: datetime, command: list[str], *, home: Path, cwd: Path) -> Path   # schedule.py; remove_once(name) -> bool
```

**Run commands in detail**

| Command | Parameters | Behavior | Exit codes |
| --- | --- | --- | --- |
| `factory run` | `[<run> ...] \| --all`, `--detach`, `--poll 5`, `--json` | Takes each run's lock and drives it until done, failed, aborted, blocked or waiting. `--detach` starts the engine in the background and returns its pid | 0, 1, 3, 4, 5 |
| `factory tick` | `--all-repos \| --repo <path>`, `--env-file <path>`, `--json` | The scheduled pass in [module 6](06-engine-core.md). Never runs a worker, and returns within seconds | 0, 1, 2 |
| `factory decide` | `<run> [--stage <s>] --packet <sha> D1=opt-a ... [--notes] [--question D1="..."] [--by] [--json]` | Records the answer, then starts an engine if none holds the lock. Answers are trailing `ID=option` tokens, in any position | 0, 2 (stale packet, bad choice, or a token that is not `ID=option`) |
| `factory add` | `"title" [--type] [--body file] [--files a.md b.md] [--repo]` | Creates the run and prints its id; starts an engine unless `--no-run` | 0, 2 |
| `factory sync` | `[--repo] [--json]` | Reads sources once and creates runs without starting engines | 0, 1 |

**Parser and entry points.** The CLI is parsed with `argparse` from the standard library, so it adds no dependency. `python -m factory_engine` is the repo engine's CLI and runs every command about a run. The `factory` console script, installed by `factory-launcher`, is the machine launcher: it handles the machine commands itself and hands every other command to the right engine.

The launcher finds the repo from the current folder, `--repo`, or, for a run id, the repo path recorded in its run.json. So `factory decide <run>` works from any folder.

**Which engine runs a command (phase 1a, owner decisions 2026-11-21).** A command about an existing run runs on the engine in that run's kit snapshot, `kits/<kit_hash>/factory/engine`, and a command that creates a run runs on the repo's committed `factory/engine`. If that folder is missing, the launcher starts nothing and fails with `kit.no_engine` (exit 2); the message names the run and says to add `--installed-engine` to the command, which runs that one command on the installed engine, for a run started before the engine was part of the kit. `abort` takes the same option, so a stuck run can be aborted. There is no automatic fall back to the installed engine.

The **router skill** maps chat phrases to these same commands and shows decision packets in the picker format. It never writes state.

- **Run and test:** `pytest factory/engine/tests/api factory/launcher/tests`, plus an end-to-end test that runs the shipped bug-fix workflow on a seeded repo, driven only through the CLI. Its `cmd` gates are stubbed through the gate runner (`gates.use_command_runner`) and its worker is scripted with `FakeWorkerAdapter`, with `FakePullRequests` for the pull request step. The run stops at the `propose` approval, is answered with `factory decide`, and finishes.
- **Decide answers:** `factory decide` takes each answer as a trailing `D1=opt-a` token, in any position among the options. argparse cannot take a variable positional list between options, so the CLI reads the leftover tokens itself with `parse_known_args`, and each one must match `ID=option`. Any other token is a usage error, exit 2.
- **Errors:** CLI misuse exits with code 2. Every command supports `--json` with the shared error shape. The router skill shows CLI messages as they are.
- **A Python that cannot import the engine's dependencies.** Importing `factory_launcher` first checks that the interpreter can import PyYAML and jsonschema (the engine's `dependencies` in `factory/engine/pyproject.toml`). If not, every launcher entry point stops with `config.invalid`, names the interpreter and the missing module, and gives the install command, exit 2, in the shared `--json` shape when `--json` is passed. The check runs before the engine is imported, so `doctor` cannot report it as a row: `doctor` itself needs the engine. The detached engine and dashboard run on `sys.executable`, the interpreter that already passed the check, so a spawn does not fail on this import.

Acceptance criteria:

- [ ] Every command documented above exists, supports `--json` and uses the shared exit codes. (not ticked: `factory plugins enable|disable` is phase 1b and does not exist yet. `watch` is tested in `factory/launcher/tests/test_watch.py`, and `where` and `events` in `factory/engine/tests/drivers/test_cli.py`. Not every other row of the table has a test yet, so this stays open)
- [x] Two repos on different kit versions are driven by their own engine through one launcher. (test: factory/launcher/tests/test_two_kit_dispatch.py::test_each_run_is_answered_by_its_own_repos_engine, ::test_a_run_keeps_its_engine_after_the_repo_moves_to_a_new_kit, ::test_tick_started_engine_runs_the_runs_own_snapshot_engine; decision 2026-11-20-which-engine-serves-each-repo, built as `docs/tasks.md` item 17)
- [x] `decide`, `retry`, `goto` and `skip` start an engine only when no live lock exists. (test: factory/engine/tests/drivers/test_cli.py::test_retry_refuses_a_run_a_live_engine_holds, ::test_goto_refuses_a_run_a_live_engine_holds, ::test_skip_refuses_a_run_a_live_engine_holds, ::test_decide_records_the_answer_but_starts_no_engine_while_a_live_engine_holds_the_run, ::test_spawn_engine_returns_none_while_a_live_lock_holds_the_run)
- [x] Two ticks fired together: the second exits at once and no run starts twice. (test: factory/launcher/tests/test_tick.py::test_a_tick_that_finds_another_tick_holding_the_lock_exits_at_once; factory/launcher/tests/test_tick.py::test_two_ticks_in_a_row_do_not_start_a_run_twice)
- [x] `tick` takes the `Config` from `load_config(None)`, with no repo part, and reads each repo's own settings through `load_config(repo)`; no `MachineConfig` type exists. (test: factory/launcher/tests/test_tick.py::test_a_tick_syncs_each_repo_with_its_own_settings)
- [x] `tick` polls open pull requests, routes red CI back to fix, and finishes runs whose PR merged. (test: factory/launcher/tests/test_tick.py::test_a_tick_starts_an_engine_for_a_run_whose_pull_request_merged_closed_or_went_red, ::test_a_tick_writes_no_run_state_when_it_reads_a_pull_request; factory/engine/tests/engine/test_merge_review.py::test_a_merged_pull_request_ends_the_run_done_and_removes_its_worktree, ::test_a_closed_pull_request_aborts_the_run, ::test_red_ci_sends_the_run_back_with_the_failing_output_as_feedback; run against FakePullRequests only, so `gh pr view` through a real GitHub is not exercised)
- [x] `schedule install` writes a working entry on Linux and macOS (launchd, cron or a systemd timer); `remove` deletes it. Windows is phase 2. (test: factory/launcher/tests/test_schedule.py::test_install_on_macos_writes_a_launchd_plist_with_the_interval; factory/launcher/tests/test_schedule.py::test_install_on_linux_writes_a_systemd_timer_and_its_service; factory/launcher/tests/test_schedule.py::test_remove_deletes_the_macos_entry_and_reports_it; factory/launcher/tests/test_schedule.py::test_remove_deletes_both_linux_units)
- [x] `schedule at` writes an OS entry that runs one command once at a local time, from the folder it was given, with its arguments intact; the entry removes itself after it runs; `remove --name` deletes one job and no other. A past or unparseable time is refused. (test: factory/launcher/tests/test_schedule.py::test_a_once_job_on_macos_fires_at_the_time_and_then_removes_itself; ::test_the_wrapper_runs_the_command_with_its_arguments_and_deletes_the_entry; ::test_the_wrapper_keeps_the_commands_exit_code; ::test_a_once_job_on_linux_writes_a_timer_for_that_date_and_its_service; ::test_remove_once_deletes_only_that_job; ::test_an_at_time_is_local_and_must_be_in_the_future; launchd fired a real job on 2026-11-22)
- [x] `init --github` composes `init_repo` (3) with `ensure_labels` (7). (test: factory/engine/tests/drivers/test_cli.py::test_init_github_creates_the_layout_and_the_factory_labels)
- [x] `factory dashboard --detach` leaves a server answering after the command returns, prints the address with the token, and exits 2 with the port's message when the port is taken. (test: factory/launcher/tests/test_dashboard_detach.py::test_detach_keeps_the_server_running_after_the_command_returns; factory/launcher/tests/test_machine_commands.py::test_dashboard_detach_json_reports_the_url_and_port_and_returns_at_once, PR #83, commit 4a1ab9e. The port-taken case was checked by hand, not by a test.)
- [x] A launcher run by a Python without PyYAML or jsonschema exits 2 with a one-line `config.invalid` error that names the interpreter, the module and the install command, with no traceback, and prints the shared JSON shape under `--json`. (test: factory/launcher/tests/test_missing_deps.py::test_a_python_without_a_runtime_dependency_stops_with_a_named_error_and_no_traceback, ::test_with_json_the_named_error_is_the_shared_error_shape_on_stdout)

## Decisions

A row changes only through a new `proposed` ADR in `docs/adr/`. To read a folded ADR in full, see `docs/adr/README.md`; the Id cell is the file name without `.md`.

| Rule | Why | Not chosen | Id |
| --- | --- | --- | --- |
| Parse the CLI with `argparse`. Two entry points: `python -m factory_engine` for the repo engine, and the `factory` console script from `factory-launcher` for the machine launcher. | `argparse` adds no dependency, and two entry points follow the split in section 18. | `click-or-typer` (a new dependency in every kit snapshot); `one-entry-point` (machine commands need no engine choice). | `2026-11-16-cli-parser-and-entry-points` (owner decision 2026-11-16) |
| `factory decide` takes its answers as trailing `ID=option` tokens, read with `parse_known_args`. Any other token is a usage error, exit 2. There is no `--choice` flag. | The spec, module 11 and the dashboard already use the positional form, and it parses on both supported Pythons. | `choice-flag-amend-spec` (edit the spec, module 11, the router skill and the dashboard); `both-forms` (two ways to do one thing). | `2026-11-17-decide-answers-are-positional-tokens` (M1) |
| A run uses the engine in its own kit snapshot, selected with `PYTHONPATH`. A missing engine fails with `kit.no_engine` unless `--installed-engine` is given. The engine copy leaves out its `tests/` folder. | A run keeps the engine it was created with, with no new dependency. The per-snapshot venv waits for phase 1b. | `per-snapshot-venv`; `launcher-installed-engine`; `fall-back-with-warning`; `engine-with-tests`. | `2026-11-20-which-engine-serves-each-repo` (owner decision 2026-11-21, D1) |
| The end-to-end CLI test runs the shipped `bug-fix` workflow on a seeded repo, driven only through the CLI, with its `cmd` gates stubbed through `gates.use_command_runner` and a scripted `FakeWorkerAdapter`. The run stops at `propose`, is answered with `factory decide`, and finishes. | The test runs a real shipped workflow, so it catches what a fixture would hide. | `keep-chore` (keep `chore` and change the spec line); `fixture-workflow` (a test-only workflow shaped like bug-fix). | 2026-11-17-cli-end-to-end-test-runs-bug-fix (chosen recommended option `bug-fix-stubbed-gates`) |
