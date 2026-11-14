"""FakeWorkerAdapter: scripted results for other modules' tests (module 9).

script maps a task id to the results of its attempts, in order. writes maps a task id to the files the
worker "writes" into its task_dir when it starts (relative path -> text). Each start() consumes the next result
for that task; asking for an attempt that was not scripted raises, so a test never passes by accident.
"""

from __future__ import annotations

from pathlib import Path

from ...types import CheckResult
from .base import AttemptResult, Capabilities, HarnessConfig, TaskContext, WorkerHandle


def ok(artifact: Path | None = None, *, input_tokens: int | None = 100, output_tokens: int | None = 50,
       models: list[str] | None = None) -> AttemptResult:
    return AttemptResult("ok", 0, artifact, input_tokens, output_tokens, models if models is not None else ["fake-model"], None)


def failed(error_kind: str = "crash", exit_code: int = 1) -> AttemptResult:
    return AttemptResult("failed", exit_code, None, None, None, [], error_kind)  # type: ignore[arg-type]


def timeout() -> AttemptResult:
    return AttemptResult("timeout", None, None, None, None, [], None)


class FakeWorkerAdapter:
    name = "fake"

    def __init__(self, script: dict[str, list[AttemptResult]], *, writes: dict[str, dict[str, str]] | None = None,
                 capabilities: Capabilities | None = None):
        self.script = {k: list(v) for k, v in script.items()}
        self.writes = writes or {}
        self.capabilities = capabilities or Capabilities(subagents="none", usage=True)
        self.started: list[TaskContext] = []   # every context a test asked the fake to run
        self.stopped: list[WorkerHandle] = []
        self._used: dict[str, int] = {}
        self.check_result = CheckResult("fake", True, "fake adapter", "")

    def check(self, conf: HarnessConfig) -> CheckResult:
        return self.check_result

    def start(self, ctx: TaskContext, conf: HarnessConfig, log: Path) -> WorkerHandle:
        results = self.script.get(ctx.task_id)
        n = self._used.get(ctx.task_id, 0)
        if results is None or n >= len(results):
            raise AssertionError(f"FakeWorkerAdapter has no scripted attempt {n + 1} for task {ctx.task_id!r}")
        self._used[ctx.task_id] = n + 1
        self.started.append(ctx)
        for rel, text in self.writes.get(ctx.task_id, {}).items():
            target = ctx.task_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(f"fake worker: task {ctx.task_id} attempt {ctx.attempt}\n")
        return WorkerHandle(ctx.task_id, ctx.attempt, {"result": results[n]})

    def wait(self, handle: WorkerHandle, timeout_s: int) -> AttemptResult:
        return handle.data["result"]

    def stop(self, handle: WorkerHandle) -> None:
        self.stopped.append(handle)
