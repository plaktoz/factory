"""The worker adapter contract (module 9). Shapes are copied from module 9's code block."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from ...skills import SkillRef
from ...types import CheckResult, HelperPolicy, McpServer, Request, RunSpec

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
    skill: SkillRef | None                        # None for a deterministic task
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
    # Fields below are not in the spec's block; each is defaulted, so the first 19 keep their order (see module 9).
    artifact_name: str = "artifact.json"          # the file the task's `out` names, in task_dir
    bash: list[str] = field(default_factory=list)  # commands the stage grants as Bash(<command>:*)
    cmd: list[str] | None = None                  # deterministic tasks: the argument list
    run: RunSpec | None = None                    # deterministic tasks: script or python
    plugin_dir: Path | None = None                # the plugin folder a script or python task runs from
    question: str | None = None                   # a task built from a question list (task_template): the question it answers
    network_domains: list[str] = field(default_factory=list)  # hosts this task may reach under srt (module 17A network)


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
