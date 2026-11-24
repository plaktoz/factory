"""Helpers for the run-concurrency tests (module 6 `Engine.run`, module 3 `max_workers`). Fixtures stay in conftest.py."""

from __future__ import annotations

import threading
import time

from factory_engine.adapters.worker.base import AttemptResult, Capabilities, WorkerHandle
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok

from engine_helpers import TRIAGE_JSON

FAN_WORKFLOW = """name: chore
type: chore
sink: pull_request
policy: {write: true, deny_paths: []}
defaults: {retries: 2, timeout_minutes: 30, checkpoint_every_minutes: 10, max_restarts: 3}
stages:
  - id: work
    tasks:
%s
"""


def write_fan_workflow(repo, names: list[str]) -> None:
    """A chore whose one stage runs each named task at once, with no `needs`."""
    tasks = "\n".join(f"      - {{id: {n}, cmd: [/usr/bin/true], out: {n}.json}}" for n in names)
    folder = repo / ".factory" / "config" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "chore.yaml").write_text(FAN_WORKFLOW % tasks)


def fan_script(run_dir, names: list[str]) -> tuple[dict, dict]:
    """The scripted attempts and files for one run of `write_fan_workflow`: triage, then each named task once."""
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))], **{n: [ok(work(n, f"{n}.json"))] for n in names}}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, **{n: {f"{n}.json": "{}"} for n in names}}
    return script, writes


class PerRunWorker:
    """One worker for several runs. Each run has its own FakeWorkerAdapter, so its scripted results and files are its
    own. A (run, task) pair in `hold` blocks in `wait` until `release`; every other task returns at once.

    `running` lists the (run, task) pairs now inside a worker, and `peak` is the most at one time."""

    name = "fake"

    def __init__(self, scripts: dict[str, tuple[dict, dict]], hold: set[tuple[str, str]] = frozenset()):
        self.capabilities = Capabilities(subagents="none", usage=True)
        self.inner = {run: FakeWorkerAdapter(script, writes=writes) for run, (script, writes) in scripts.items()}
        self.gates = {key: threading.Event() for key in hold}
        self.running: list[tuple[str, str]] = []
        self.peak = 0
        self._lock = threading.Lock()

    def check(self, conf):
        return next(iter(self.inner.values())).check(conf)

    def start(self, ctx, conf, log):
        handle = self.inner[ctx.run_id].start(ctx, conf, log)
        with self._lock:
            self.running.append((ctx.run_id, ctx.task_id))
            self.peak = max(self.peak, len(self.running))
        return WorkerHandle(ctx.task_id, ctx.attempt, {"run": ctx.run_id, "inner": handle})

    def wait(self, handle, timeout_s):
        key = (handle.data["run"], handle.task_id)
        gate = self.gates.get(key)
        if gate is not None:
            gate.wait(20)
        with self._lock:
            self.running.remove(key)
        return self.inner[key[0]].wait(handle.data["inner"], timeout_s)

    def stop(self, handle):
        gate = self.gates.get((handle.data["run"], handle.task_id))
        if gate is not None:
            gate.set()
        self.inner[handle.data["run"]].stop(handle.data["inner"])

    def release(self, run: str, task: str) -> None:
        self.gates[(run, task)].set()

    def release_all(self) -> None:
        for gate in self.gates.values():
            gate.set()


def wait_until(cond, seconds: float = 20) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def settle(worker, quiet_for: float = 1.0) -> None:
    """Wait until no worker has started for `quiet_for` seconds, so a limit shows as a start that does not happen."""
    last, since = len(worker.running), time.time()
    while time.time() - since < quiet_for:
        time.sleep(0.05)
        now = len(worker.running)
        if now != last:
            last, since = now, time.time()


__all__ = ["AttemptResult", "PerRunWorker", "fan_script", "settle", "wait_until", "write_fan_workflow"]
