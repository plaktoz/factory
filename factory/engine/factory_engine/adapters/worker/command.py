"""CommandAdapter (module 9): deterministic tasks (cmd, script, python), each under `srt` with the worker's rules.

`capabilities` is {subagents: none, usage: false}, so 6B schedules these like any task and no usage record is written.
The exit-code rules differ by kind. A `cmd` (and a gate command) is checked by exit 0 against anything else: 0 passes,
any other exit is a check failure, and a missing binary is a task error. A script or python task maps 0 to passed, 1
to a check failure, and 2 or more to a task error. The adapter reports the raw exit code and the attempt exit; module
8 applies the mapping (see `classify_exit`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ...errors import FactoryError
from ...types import CheckResult, RunSpec
from . import sandbox
from .base import AttemptResult, Capabilities, HarnessConfig, TaskContext, WorkerHandle
from .runtime import (LogTail, attempt_folder, base_env, cache_env, kill_group, read_text, remove_attempt, wait_tailing,
                      write_log, write_private)

PASS, CHECK_FAILED, TASK_ERROR = "passed", "check_failed", "task_error"


def classify_exit(kind: str, exit_code: int | None) -> str:
    """Maps an exit code to a result for each task kind (module 9, module 5). Kinds: "cmd" or "script" (also "python")."""
    if exit_code is None:
        return TASK_ERROR
    if kind == "cmd":
        return PASS if exit_code == 0 else CHECK_FAILED
    if exit_code == 0:
        return PASS
    if exit_code == 1:
        return CHECK_FAILED
    return TASK_ERROR


def script_argv(script: Path, args: list[str]) -> list[str]:
    """How a plugin script runs (module 5): `.py` with the engine's Python, `.sh` with sh, an executable file directly.
    A `.ps1` script is Windows only, and Windows is phase 2."""
    ext = script.suffix
    if ext == ".py":
        return [sys.executable, str(script), *args]
    if ext == ".sh":
        return ["sh", str(script), *args]
    if ext != ".ps1" and os.access(script, os.X_OK):
        return [str(script), *args]
    raise FactoryError("config.invalid", f"script {script} has no runner for {ext or 'no extension'}",
                       hint="use a .py script, an executable file, or a .sh script (.ps1 is Windows, phase 2)")


class CommandAdapter:
    name = "command"
    capabilities = Capabilities(subagents="none", usage=False)

    def __init__(self, environ: dict[str, str] | None = None):
        self.environ = dict(os.environ if environ is None else environ)

    def check(self, conf: HarnessConfig) -> CheckResult:
        return sandbox.check_srt()

    def _env(self, ctx: TaskContext) -> dict[str, str]:
        env = base_env(self.environ)
        env.update({"FACTORY_RUN_ID": ctx.run_id, "FACTORY_STAGE": ctx.stage, "FACTORY_TASK_ID": ctx.task_id,
                    "FACTORY_WORKTREE": str(ctx.worktree), "FACTORY_TASK_DIR": str(ctx.task_dir)})
        env.update(cache_env(ctx.task_dir))
        return env

    def _inner(self, ctx: TaskContext) -> tuple[str, list[str], str]:
        """The program's argument list, its kind and the directory it runs in."""
        if ctx.run is None and ctx.cmd is not None:
            if not ctx.cmd:
                raise FactoryError("config.invalid", f"task {ctx.task_id}: cmd is an empty list",
                                   hint="give the command as a list of strings, for example [make, test]")
            return "cmd", list(ctx.cmd), str(ctx.worktree)
        if ctx.run is None:
            raise FactoryError("config.invalid", f"task {ctx.task_id}: no cmd, script or python", hint="set one of cmd, run")
        run: RunSpec = ctx.run
        if run.script is not None:
            base = ctx.plugin_dir or ctx.worktree
            script = (base / run.script).resolve()
            if not script.is_file():
                raise FactoryError("config.invalid", f"task {ctx.task_id}: script {run.script} is not in the plugin",
                                   hint="check the path under the plugin folder")
            return "script", script_argv(script, list(run.args)), str(ctx.worktree)
        runner = [sys.executable, "-m", "factory_engine.plugin_runner", str(ctx.plugin_dir or ctx.worktree), run.python or ""]
        return "python", runner, str(ctx.worktree)

    def _settings(self, ctx: TaskContext, folder: Path) -> Path:
        # Only this task's own hosts go in; a task with none gets the empty allowance (module 9, module 17A `network`).
        path = folder / "srt-settings.json"
        write_private(path, json.dumps(sandbox.srt_settings(ctx.worktree, ctx.task_dir, domains=ctx.network_domains)))
        return path

    def start(self, ctx: TaskContext, conf: HarnessConfig, log: Path) -> WorkerHandle:
        ctx.task_dir.mkdir(parents=True, exist_ok=True)
        bin_ = sandbox.require_srt()
        folder = attempt_folder(f"{ctx.task_id}-cmd")
        try:
            settings = self._settings(ctx, folder)
            kind, argv, cwd = self._inner(ctx)
            wrapped = sandbox.srt_command(bin_, settings, argv)
            env = self._env(ctx)
            if kind == "python":
                env["PYTHONPATH"] = os.pathsep.join([str(Path(__file__).resolve().parents[3]), *filter(None, [env.get("PYTHONPATH")])])
            # Output goes to the task folder: srt confines a child's writes to the worktree and that folder, so a file
            # under the attempt folder (in the denied factory home) would be refused inside the sandbox.
            out_path, err_path = ctx.task_dir / "stdout.txt", ctx.task_dir / "stderr.txt"
            stdin_path = folder / "stdin.json"
            write_private(stdin_path, json.dumps({k: v for k, v in env.items() if k.startswith("FACTORY_")}))
            with open(stdin_path) as stdin_f, open(out_path, "w") as stdout_f, open(err_path, "w") as stderr_f:
                try:
                    proc = subprocess.Popen(wrapped, cwd=cwd, env=env, stdout=stdout_f, stderr=stderr_f,
                                            stdin=stdin_f if kind == "python" else subprocess.DEVNULL,
                                            start_new_session=True)
                except FileNotFoundError:
                    proc = None
        except BaseException:
            remove_attempt(folder)
            raise
        return WorkerHandle(ctx.task_id, ctx.attempt, {
            "proc": proc, "kind": kind, "folder": folder, "log": log, "task_dir": ctx.task_dir,
            "argv": argv, "stdout": out_path, "stderr": err_path, "stopped": False,
            "artifact": ctx.task_dir / ctx.artifact_name})

    def wait(self, handle: WorkerHandle, timeout_s: int) -> AttemptResult:
        data = handle.data
        proc = data["proc"]
        if proc is None:
            write_log(data["log"], f"command: {data['argv'][0]!r} is not installed\n", [])
            remove_attempt(data["folder"])
            return AttemptResult("failed", None, None, None, None, [], "binary_missing")
        try:
            tail = LogTail(data["log"], [(data["stdout"], str), (data["stderr"], str)], [])
            rc = wait_tailing(proc, timeout_s, tail)
        except subprocess.TimeoutExpired:
            kill_group(proc)
            rc = None
        self._finish_log(data)
        if rc is None:
            return AttemptResult("timeout", None, None, None, None, [], None)
        if data.get("stopped") or rc < 0:
            return AttemptResult("killed", rc if rc >= 0 else None, None, None, None, [], None)
        if rc != 0:
            return AttemptResult("failed", rc, None, None, None, [], None)
        # A command writes its own `out` file into the task folder (module 9). The engine marks the task done only
        # when this returns the file, so a command that exits 0 without writing it is not done.
        artifact = data["artifact"] if data["artifact"].is_file() else None
        return AttemptResult("ok", rc, artifact, None, None, [], None)

    def _finish_log(self, data: dict) -> None:
        """Copies the captured output into worker.log, then deletes the capture files and the attempt folder."""
        write_log(data["log"], read_text(data["stdout"]) + read_text(data["stderr"]), [])
        for key in ("stdout", "stderr"):
            data[key].unlink(missing_ok=True)
        remove_attempt(data["folder"])

    def stop(self, handle: WorkerHandle) -> None:
        proc = handle.data.get("proc")
        if proc is not None and proc.poll() is None:
            kill_group(proc)
        handle.data["stopped"] = True

