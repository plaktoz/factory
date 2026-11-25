"""Shared and frozen cross-module types (section 18).

Every field list below is checked against the spec by tests/contracts/test_types_match_spec.py.
Policy and Defaults take their fields from the workflow YAML in module 5; Config is in config.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from .config import Config
from .errors import ErrorKind, FactoryError  # noqa: F401  (re-exported: section 18 lists them with the shared types)

RunStatus = Literal["pending", "running", "retrying", "awaiting_approval", "blocked", "done", "failed", "aborted"]
TaskStatus = Literal["pending", "waiting", "running", "restarting", "interrupted", "done", "failed"]
Channel = Literal["cli", "dashboard", "chat", "file"]


@dataclass(frozen=True)
class RunRef:
    repo: Path
    repo_key: str
    run_id: str
    run_dir: Path


@dataclass
class Source:
    type: Literal["cli", "markdown", "github"]
    ref: str
    title: str
    body: str
    labels: list[str]
    author: str | None
    files: list[Path]


@dataclass
class Request:
    request_id: str
    source: Source
    body_sha: str
    repo: str
    title: str
    type: str | None
    type_source: str | None
    priority: str | None
    acceptance: list[str]


@dataclass
class AttentionItem:
    kind: Literal["approval", "decision", "triage", "blocked", "merge_review", "request_changed"]
    run_id: str
    stage: str | None
    since: str
    summary: str
    page: Path | None
    command: str | None


@dataclass
class GateResult:
    passed: bool
    gate: str
    code: str
    output_tail: str
    details: dict


class Clock(Protocol):
    def now(self) -> datetime: ...

    def sleep(self, seconds: float) -> None: ...


@dataclass
class GateSpec:
    kind: Literal["cmd", "check", "schema"]
    cmd: list[str] | None
    check: str | None
    schema: str | None
    args: dict
    skippable: bool = False


@dataclass
class RunSpec:
    script: str | None
    python: str | None
    args: list[str]

    def __post_init__(self) -> None:
        # exactly one of script and python is set; a load error otherwise (decision Q4)
        if (self.script is None) == (self.python is None):
            raise FactoryError("config.invalid", "run: set exactly one of script and python")


@dataclass
class OnFail:
    goto: str
    max: int


@dataclass
class HelperPolicy:
    mode: Literal["auto", "native", "off"]
    max: int
    split_hints: list[str]
    timeout_minutes: int | None


@dataclass
class McpServer:
    name: str
    url: str | None
    command: list[str] | None
    headers: dict[str, str]
    env: dict[str, str]


@dataclass
class StageState:
    id: str
    visit: int
    status: Literal["pending", "running", "awaiting_approval", "done", "failed", "skipped"]
    tasks: list[str]
    started: str | None
    ended: str | None


@dataclass
class InfraWait:
    since: str
    tries: int
    last_error: str


@dataclass
class PrRef:
    number: int
    url: str
    head: str
    base: str


@dataclass
class PrState:
    state: Literal["open", "merged", "closed"]
    ci: Literal["green", "red", "pending"]
    checks_output: str
    review_decision: str | None


@dataclass
class Signals:
    behind_base: int
    overlaps: list[tuple[str, list[str]]]  # (other run id, files)


@dataclass
class Run:
    run_id: str
    repo: str
    repo_key: str
    repo_path: Path
    request: Request
    workflow: str | None
    branch: str | None
    worktree: Path
    status: RunStatus
    stage: str | None
    stages: list[StageState]
    loops: dict[str, int]
    attention: AttentionItem | None
    pr: PrRef | None
    signals: Signals | None
    heartbeat: str
    kit_hash: str
    infra_wait: InfraWait | None
    paths: dict[str, str] = field(default_factory=dict)


@dataclass
class GateContext:
    run: Run
    stage: str
    task_id: str | None
    worktree: Path
    task_dir: Path | None
    artifact: Path | None
    task_base: str | None
    scope: list[str]
    deny: list[str]
    cfg: Config


@dataclass
class TaskBranch:
    task_id: str
    branch: str
    task_base: str


@dataclass
class JoinResult:
    ok: bool
    conflict_files: list[str]
    hook_failed: bool
    commits: list[str]
    hook_output: str | None = None  # the failing repo hook's output (stderr then stdout, last 200 lines); None otherwise


@dataclass
class SyncResult:
    ok: bool
    conflict_files: list[str]


@dataclass
class TaskState:
    task_id: str
    stage: str
    status: TaskStatus
    attempt: int
    restarts: int
    task_base: str | None
    worktree: Path | None
    checkpoints: int
    # Process group of the attempt's worker, set while it runs and cleared when it ends. A task.json written before the
    # field existed has none, so it is optional in task.schema.json (schemagen.OPTIONAL_FIELDS).
    worker_pgid: int | None = None


@dataclass
class Event:
    seq: int
    ts: str
    type: str
    run_id: str
    data: dict


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    hint: str


@dataclass
class Problem:
    file: str
    line: int | None
    message: str
    hint: str


@dataclass
class UsageRecord:
    run_id: str
    task_id: str
    stage: str
    attempt: int
    harness: str
    model_requested: str | None
    models: list[str]
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    start: str
    end: str | None
    exit: Literal["started", "ok", "failed", "interrupted"]
    repo: str
    branch: str | None
    worktree: Path


# Workflow, Stage and TaskSpec are defined by module 5 and owned here so 5 and 8 never import each other.


@dataclass
class Policy:
    write: bool
    deny_paths: list[str]


@dataclass
class Defaults:
    retries: int
    timeout_minutes: int
    checkpoint_every_minutes: int
    max_restarts: int


DEFAULT_MAX_INTERRUPTIONS = 3  # module 8: a task's Nth engine-crash interruption fails it, so the default fails on the 3rd


@dataclass
class TaskSpec:
    id: str
    skill: str | None
    cmd: list[str] | None
    run: RunSpec | None
    scope: list[str]
    deny: list[str]
    needs: list[str]
    helpers: HelperPolicy
    out: str | None
    timeout_minutes: int
    retries: int
    model: str | None
    when: dict | None
    max_interruptions: int = DEFAULT_MAX_INTERRUPTIONS
    # Hosts this one task may reach under srt, from its language profile step's `network` key (module 17A). Empty unless
    # a profile names them, so every other task keeps the sandbox's empty allowance (module 9).
    network_domains: list[str] = field(default_factory=list)
    # Mach services this one task may look up under srt, from the same key (Go's TLS trust). Empty unless a profile names one.
    network_mach: list[str] = field(default_factory=list)


@dataclass
class Stage:
    id: str
    needs: list[str]
    tasks: list[TaskSpec]
    tasks_from: str | None
    join: str
    gate: list[GateSpec]
    on_fail: OnFail | None
    on_conflict: OnFail | None
    approval: str
    on_reject: str | None
    sync_base: bool
    source: str  # workflow or plugin:<name>
    # With tasks_from: the fields each generated task starts from; each item is then {id, question} (owner decision
    # D2, 2026-11-21). Defaulted, so the fields above keep the spec's order.
    task_template: dict | None = None


@dataclass
class Workflow:
    name: str
    type: str
    sink: str
    policy: Policy
    defaults: Defaults
    stages: list[Stage]
    regenerate_at_join: list[str]
    join_cmd: list[str] | None
    shared_files: dict[str, str]
