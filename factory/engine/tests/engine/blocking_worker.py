"""A worker fake whose `wait` blocks until the test releases it (module 6B tests)."""

from __future__ import annotations

class BlockingWorker:
    """A worker whose `wait` blocks until the test releases it, so a test can act while a worker is running.

    It wraps FakeWorkerAdapter for the scripted results. Each attempt gets its own gate. `release(task_id)` opens the
    gate of the attempt that is running, or of the task's next attempt when none is running. `stop` makes a blocked
    wait return `killed`, as a real adapter does."""

    name = "fake"

    def __init__(self, inner):
        import threading
        self.inner = inner
        self.capabilities = inner.capabilities
        self.gates: dict[str, threading.Event] = {}
        self.preset: set[str] = set()
        self.killed: set[str] = set()
        self.running: list[str] = []
        self.peak = 0
        self._lock = threading.Lock()
        self._threading = threading

    def check(self, conf):
        return self.inner.check(conf)

    def start(self, ctx, conf, log):
        handle = self.inner.start(ctx, conf, log)
        with self._lock:
            gate = self._threading.Event()
            if ctx.task_id in self.preset:
                self.preset.discard(ctx.task_id)
                gate.set()
            self.gates[ctx.task_id] = gate
            self.running.append(ctx.task_id)
            self.peak = max(self.peak, len(self.running))
        return handle

    def wait(self, handle, timeout_s):
        from factory_engine.adapters.worker.fake import AttemptResult
        gate = self.gates[handle.task_id]
        gate.wait(20)
        with self._lock:
            if handle.task_id in self.running:
                self.running.remove(handle.task_id)
        if handle.task_id in self.killed:
            self.killed.discard(handle.task_id)
            return AttemptResult("killed", None, None, None, None, [], None)
        return self.inner.wait(handle, timeout_s)

    def stop(self, handle):
        self.killed.add(handle.task_id)
        self.gates[handle.task_id].set()
        self.inner.stop(handle)

    def release(self, task_id):
        with self._lock:
            if task_id in self.running:
                self.gates[task_id].set()
            else:
                self.preset.add(task_id)
