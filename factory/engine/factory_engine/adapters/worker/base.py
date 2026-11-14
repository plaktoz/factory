"""The worker adapter contract (module 9). Shapes are copied from module 9's code block."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from ...skills import SkillRef  # noqa: F401  (module 10 defines it; wave 0 had a stand-in here)
from ...types import CheckResult, HelperPolicy, McpServer, Request

AttemptExit = Literal["ok", "failed", "timeout", "killed"]
ErrorKindWorker = Literal["auth", "rate_limit", "binary_missing", "model_not_found", "crash"]


@dataclass
class Capabilities:
    subagents: Literal["native", "none"]
    usage: bool


@dataclass
class HarnessConfig:
    """What resolve_harness (module 3) returns: command, model (None when unset), args, resolved env."""

    command: str
    model: str | None
    args: list[str]
    env: dict[str, str]


@dataclass
class TaskContext:
    run_id: str
    task_id: str
    stage: str
    attempt: int
    skill: SkillRef
    request: Request
    worktree: Path
    task_dir: Path
    scope: list[str]
    deny: list[str]
    helpers: HelperPolicy
    feedback: list[Path]
    notes: list[str]
    progress: Path | None
    output_schema: str | None
    model: str | None
    mcp: list[McpServer]
    practices: list[SkillRef]


@dataclass
class AttemptResult:
    exit: AttemptExit
    exit_code: int | None
    artifact: Path | None
    input_tokens: int | None
    output_tokens: int | None
    models_observed: list[str]
    error_kind: ErrorKindWorker | None


@dataclass
class WorkerHandle:
    """Opaque to callers. Real adapters keep a process group here; the fake keeps its script position."""

    task_id: str
    attempt: int
    data: dict = field(default_factory=dict)


class WorkerAdapter(Protocol):
    name: str
    capabilities: Capabilities

    def check(self, conf: HarnessConfig) -> CheckResult: ...

    def start(self, ctx: TaskContext, conf: HarnessConfig, log: Path) -> WorkerHandle: ...

    def wait(self, handle: WorkerHandle, timeout_s: int) -> AttemptResult: ...

    def stop(self, handle: WorkerHandle) -> None: ...
