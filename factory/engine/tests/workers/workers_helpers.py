"""Plain helpers for the module 9 worker tests. Fixtures stay in conftest.py; tests import these by their own module name."""

from pathlib import Path

from factory_engine.adapters.worker.base import HarnessConfig, TaskContext
from factory_engine.skills import SkillRef
from factory_engine.types import HelperPolicy, Request, Source


HERE = Path(__file__).resolve().parent
RECORDED = HERE / "recorded"
ENV_GW = {"ANTHROPIC_AUTH_TOKEN": "tok-gateway-SECRET-123", "ANTHROPIC_BASE_URL": "https://gw.example.test"}


def request() -> Request:
    src = Source("cli", "acme/report#1", "Fix the total", "The total is wrong.", ["bug"], "alice", [])
    return Request("gh-1", src, "sha", "report", "Fix the total", "bug", "label", "high", ["total matches the sum"])


_DEFAULT = object()


def ctx_for(worktree: Path, task_dir: Path, *, task_id: str = "backend", attempt: int = 1,
            model: str | None = None, helpers: HelperPolicy | None = None, mcp=None, bash=None,
            artifact_name: str = "stage.json", skill=_DEFAULT) -> TaskContext:
    """A task context for an LLM stage by default. Pass skill=None for a deterministic task."""
    if skill is _DEFAULT:
        skill = SkillRef("fix", "own", worktree.parent / "skill", {})
    return TaskContext(run_id="run-1", task_id=task_id, stage="fix", attempt=attempt, skill=skill, request=request(),
                       worktree=worktree, task_dir=task_dir, scope=["src/**"], deny=["secrets/**"],
                       helpers=helpers or HelperPolicy("off", 0, [], None), feedback=[], notes=[], progress=None,
                       output_schema="stage-report", model=model, mcp=list(mcp or []), practices=[],
                       artifact_name=artifact_name, bash=list(bash or []))


def harness(command: str, env: dict | None = None, model: str | None = None, args: list | None = None) -> HarnessConfig:
    return HarnessConfig(command=command, model=model, args=list(args or []), env=dict(env or {}))


def log_seen_while_running(adapter, handle, log: Path, needle: str, limit_s: float = 30.0) -> tuple[bool, bool]:
    """Runs adapter.wait in a thread and polls worker.log until `needle` is in it. Returns (seen, still_running).
    The worker is stopped before this returns."""
    import threading
    import time
    t = threading.Thread(target=lambda: adapter.wait(handle, 120), daemon=True)
    t.start()
    seen, deadline = False, time.monotonic() + limit_s
    while time.monotonic() < deadline and not seen:
        seen = log.is_file() and needle in log.read_text()
        if not seen:
            time.sleep(0.1)
    running = t.is_alive()
    adapter.stop(handle)
    t.join(30)
    return seen, running
