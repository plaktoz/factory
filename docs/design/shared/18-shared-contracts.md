# 18. Shared contracts

Part of the [phase 1 design](../phase-1.md#shared-sections).

These are the types, conventions and package layout every module codes against. Freeze them first; each module can then be built and tested in parallel against fakes of its upstream modules. Each module's own interface is in its **Module contract** block.

**Package layout and ownership**

| File or folder | Module |
| --- | --- |
| `types.py` (the shared and frozen types below, plus `Workflow`, `Stage` and `TaskSpec`, which module 5 defines), `errors.py` | 18 Shared contracts |
| `config.py`, `kit.py` | 3 Kit and configuration |
| `intake.py`, `triage.py` | 4 Intake and triage |
| `workflow.py`, `plugins.py` | 5 Workflows and plugins |
| `state.py` | 6A State store |
| `engine.py` | 6B Engine loop |
| `gitops.py`, `adapters/tracker/`, `prs.py` | 7 Git and GitHub |
| `gates.py`, `rework.py`, `checks.py` | 8 Gates, error handling and rework |
| `adapters/worker/`, `prompt.py` | 9 Worker adapters |
| `skills.py`, `shims.py` | 10 Skills |
| `decisions.py`, `page.py`, `notify.py` | 11 Human stops |
| `notes.py` | 12 Live view and steering |
| `delivery.py`, `summary.py` | 13 Delivery |
| `usage.py` | 14 Token tracking |
| `server.py`, `dashboard/` | 15 Dashboard |
| `api.py`, `cli.py`, `launcher/`, `tick.py` | 16 Drivers |
| `housekeeping.py` | 17 Housekeeping |

**Shared types** (`types.py`)

```python
RunStatus  = Literal["pending", "running", "retrying", "awaiting_approval", "blocked", "done", "failed", "aborted"]
TaskStatus = Literal["pending", "waiting", "running", "restarting", "interrupted", "done", "failed"]
Channel    = Literal["cli", "dashboard", "chat", "file"]

@dataclass(frozen=True)
class RunRef:      repo: Path; repo_key: str; run_id: str; run_dir: Path

@dataclass
class Source:      type: Literal["cli", "markdown", "github"]; ref: str; title: str; body: str
                   labels: list[str]; author: str | None; files: list[Path]

@dataclass
class Request:     request_id: str; source: Source; body_sha: str; repo: str; title: str
                   type: str | None; type_source: str | None; priority: str | None; acceptance: list[str]

@dataclass
class Run:         run_id: str; repo: str; repo_key: str; repo_path: Path; request: Request; workflow: str | None
                   branch: str | None; worktree: Path; status: RunStatus; stage: str | None
                   stages: list[StageState]; loops: dict[str, int]; attention: AttentionItem | None
                   pr: PrRef | None; signals: Signals | None; heartbeat: str
                   kit_hash: str; infra_wait: InfraWait | None; paths: dict[str, str]

@dataclass
class AttentionItem: kind: Literal["approval", "decision", "triage", "blocked", "merge_review", "request_changed"]
                   run_id: str; stage: str | None; since: str; summary: str
                   page: Path | None; command: str | None

@dataclass
class GateResult:  passed: bool; gate: str; code: str; output_tail: str; details: dict

ErrorKind = Literal["fail_fast", "transient", "task_retry", "rework", "human"]

class FactoryError(Exception):
    code: str       # "<module>.<reason>", such as "config.missing_env", "git.push_rejected"
    message: str    # what happened
    hint: str       # what to do
    kind: ErrorKind
```

**Frozen cross-module types** (`types.py`)

These 21 types, `ErrorKind` above and the 20 below, are used by two or more modules, or appear in a field of a shared type. Their shapes were accepted on 2026-11-14 (decision R1, see [open decisions](../../reviews/open-decisions.md)), so every module in waves 1 to 3 and every wave 0 fake codes to one shape. A change to one of them is made in this section and in every module in its **Used by** cell, in the same commit.

```python
# types.py
class Clock(Protocol):
    def now(self) -> datetime: ...
    def sleep(self, seconds: float) -> None: ...

@dataclass
class GateSpec:       kind: Literal["cmd", "check", "schema"]; cmd: list[str] | None
                      check: str | None; schema: str | None; args: dict

@dataclass
class GateContext:    run: Run; stage: str; task_id: str | None; worktree: Path
                      task_dir: Path | None; artifact: Path | None; task_base: str | None
                      scope: list[str]; deny: list[str]; cfg: Config

@dataclass
class RunSpec:        script: str | None; python: str | None; args: list[str]
                      # exactly one of script and python is set; a load error otherwise

@dataclass
class OnFail:         goto: str; max: int

@dataclass
class HelperPolicy:   mode: Literal["auto", "native", "off"]; max: int
                      split_hints: list[str]; timeout_minutes: int | None

@dataclass
class McpServer:      name: str; url: str | None; command: list[str] | None
                      headers: dict[str, str]; env: dict[str, str]

@dataclass
class StageState:     id: str; visit: int
                      status: Literal["pending", "running", "awaiting_approval", "done", "failed", "skipped"]
                      tasks: list[str]; started: str | None; ended: str | None

@dataclass
class InfraWait:      since: str; tries: int; last_error: str

@dataclass
class PrRef:          number: int; url: str; head: str; base: str

@dataclass
class PrState:        state: Literal["open", "merged", "closed"]; ci: Literal["green", "red", "pending"]
                      checks_output: str; review_decision: str | None

@dataclass
class Signals:        behind_base: int; overlaps: list[tuple[str, list[str]]]   # (other run id, files)

@dataclass
class TaskBranch:     task_id: str; branch: str; task_base: str

@dataclass
class JoinResult:     ok: bool; conflict_files: list[str]; hook_failed: bool; commits: list[str]

@dataclass
class SyncResult:     ok: bool; conflict_files: list[str]

@dataclass
class TaskState:      task_id: str; stage: str; status: TaskStatus; attempt: int; restarts: int
                      task_base: str | None; worktree: Path | None; checkpoints: int

@dataclass
class Event:          seq: int; ts: str; type: str; run_id: str; data: dict

@dataclass
class CheckResult:    name: str; ok: bool; detail: str; hint: str

@dataclass
class Problem:        file: str; line: int | None; message: str; hint: str

@dataclass
class UsageRecord:    run_id: str; task_id: str; stage: str; attempt: int; harness: str
                      model_requested: str | None; models: list[str]
                      input_tokens: int | None; output_tokens: int | None; total_tokens: int | None
                      start: str; end: str | None; exit: Literal["started", "ok", "failed", "interrupted"]
                      repo: str; branch: str | None; worktree: Path
```

| Type | Used by | Shape taken from |
| --- | --- | --- |
| `Clock` | 6, 8, 11, 17, every test | `SystemClock` and `FakeClock` implement it |
| `GateSpec`, `GateContext` | 4, 5, 7, 8, 9, 11, 17A | `gate:` entries in the workflow YAML (5), the `check_*` functions, and the JSON a plugin check reads (5) |
| `RunSpec` | 5, 9 | `run: {script, args}` and `run: {python}` in the plugin manifest (5) |
| `OnFail` | 5, 8 | `on_fail: {goto, max}` in the workflow YAML |
| `HelperPolicy` | 5, 9 | `helpers: {mode, max, split_hints}` and the Declare control in 9 |
| `McpServer` | 3, 9 | `mcp_servers:` in the machine file (9) |
| `StageState`, `InfraWait` | 6, 15 | The `Run` fields above, D4 visits and D13 outages |
| `PrRef`, `PrState` | 6, 7, 13 | The comments on `PullRequests.state` and `watch_pr` |
| `Signals` | 6, 7, 15 | The `behind_base, overlaps` comment in 7 |
| `TaskBranch`, `JoinResult`, `SyncResult` | 6, 7, 8 | The comments on `join` and `sync_base` |
| `TaskState` | 6, 8, 12 | `task.json`, `TaskStatus`, D12 and the restart cap |
| `Event` | 6, 12, 15 | The `events.jsonl` catalogue in 6, including `run_snapshot` (decision E1) |
| `CheckResult`, `Problem` | 3, 5, 9, 10, 16 | `doctor`, `validate_workflow`, `verify_lock` |
| `UsageRecord` | 13, 14, 15, 16 | The `usage.jsonl` table in 14, with P4 |
| `ErrorKind` | 8, 19 | The five handling types in [section 19](19-error-handling-types.md) |

**Commands are argument lists.** `GateSpec.cmd`, `TaskSpec.cmd` and `Workflow.join_cmd` hold a list of strings, never a shell string. A string in a workflow or plugin file fails at load with `config.invalid`, the file, the line and the list form to write. The decision is Q3 in [open decisions](../../reviews/open-decisions.md).

**`Config`.** `Config` is the one configuration type. It has a `.machine` part, read from the machine file, and a `.repo` part, read from `.factory/config/`. `load_config(repo)` ([module 3](../modules/03-kit-and-configuration.md)) builds it, and `.repo` is `None` when `repo` is `None`. A function that runs without a repo, such as `tick` ([module 16](../modules/16-drivers.md)), takes a `Config` loaded that way. The keys of each part are defined by the schemas in module 3, not here.

The JSON Schemas in `factory/schemas/` are the source of truth for every file; the dataclasses mirror them, and a test checks that both stay in step. `TaskState` is written as `task`, `UsageRecord` as `usage` and `Event` as `event`.

**Conventions**

- Functions take paths and `Config` explicitly, and modules do not read globals or the current folder.
- No module imports `engine.py` or `api.py`. Only drivers (16) compose modules; only the engine loop (6B) runs the scheduling.
- **Writing run state:** only the process holding a run's lock writes `run.json` and `task.json`. Any process may append to `events.jsonl` through `state.append_event`, which takes a short file lock.
- **Errors and events:** every function that changes state emits an event. Failures raise `FactoryError` with a namespaced code, never a bare exception.
- **Fakes for parallel work:** each module that others call ships a fake, so downstream modules can be tested before it exists. The fakes are `FakeWorkerAdapter` (9), `FakeTracker` and `FakePullRequests` (7), and `FakeClock` (18), which implements `Clock` as `SystemClock` does.
- **Two install layers:**
  - The machine-level launcher (`factory`) handles the machine commands: `tick`, `dashboard`, `inbox`, `config init`, `doctor`, `schedule`.
  - It hands every command about a run to that run's own engine, `python -m factory_engine` from the run's kit snapshot, and every command that creates a run to the repo's committed kit, so repos and runs on different kit versions coexist.
  - The dashboard makes its writes by calling the launcher with `--json`, which puts each write through the right engine version.

**CLI exit codes** (all commands)

| Code | Meaning |
| --- | --- |
| 0 | Success, or the run is done |
| 1 | Failed or unexpected error |
| 2 | Invalid input or config (`fail_fast`) |
| 3 | Waiting on a human |
| 4 | Run blocked |
| 5 | Run locked by another engine |

With `--json`, every command prints one JSON object: `{"ok": bool, "code": str, "message": str, "hint": str, "data": {...}}`.

**Error-code catalogue** (decision G3, 2026-11-14)

Every `FactoryError.code` is `<module>.<reason>` and is listed here with its `ErrorKind` and a hint. A module adds its own rows in the wave that builds it. A test fails when a code is raised and not listed, and when a listed code is never raised. Codes the spec already names are the first rows. The `sandbox.*` rows come from the `failIfUnavailable` tests of 2026-11-14 and are listed in full below.

| Code | Kind | Hint |
| --- | --- | --- |
| `config.invalid` | `fail_fast` | Name the file, the line and the form to write |
| `state.locked` | `fail_fast` | Another engine holds the run; exit 5 |
| `git.hook_failed` | `human` | Show the hook output |
| `skills.unknown` | `fail_fast` | No override, locked skill or own skill matches the name; add one (module 10: with no fallback it fails fast at workflow load) |
| `git.network` | `transient` | A GitHub or network call failed on a rate limit, a timeout or a lost connection; retry with backoff (module 7) |
| `git.index_locked` | `transient` | `index.lock` is held by another git process; retry with backoff (module 7) |
| `git.push_rejected` | `human` | A push was rejected after one base sync and one retry; show the rejection (module 7) |
| `git.auth_expired` | `human` | GitHub login has expired; run `gh auth login` (module 7) |
| `git.path_exists` | `fail_fast` | A worktree or branch path already exists; name the path (module 7) |
| `git.command_failed` | `task_retry` | A git command failed and matches no other git code; the message holds git's stderr. Not a catch-all for the codes above (module 7) |
| `git.worktree_dirty` | `human` | A worktree with changes was not removed; show the files, and a removal only with force (module 7) |
| `notes.task_finished` | `fail_fast` | A note for a finished task is refused |
| `gate.command_missing` | `human` | A gate command's binary was not found, so the gate did not run; install it or fix the command (module 8) |
| `sandbox.unavailable` | `human` | The OS refused to start the sandbox (`sandbox_apply: Operation not permitted`, exit 71) |
| `sandbox.settings_invalid` | `fail_fast` | The settings file parses but a field fails validation; name the field |
| `sandbox.settings_unreadable` | `fail_fast` | The `--settings` file is missing or unreadable; name the path |
| `sandbox.settings_unparseable` | `fail_fast` | The settings file is not JSON. Claude runs with **no sandbox** on such a file, so the adapter parses the file before it starts the worker |
| `sandbox.srt_missing` | `fail_fast` | `srt` is not installed; give the install command |
| `sandbox.node_old` | `fail_fast` | Node is older than 22.12, which `srt` needs |
| `sandbox.canary_open` | `human` | `doctor` found a read or write route that is not blocked; name the route |
| `config.no_credentials` | `fail_fast` | Set `ANTHROPIC_API_KEY`, or `ANTHROPIC_AUTH_TOKEN` with `ANTHROPIC_BASE_URL`; a login session is not supported in phase 1 |

**Versions.** Python 3.10 is the floor and the tests also run on the newest Python installed (decision G9, below). Node 22.12 is the floor for `srt`, and the factory is tested on Node 26 (decision, 2026-11-14).
