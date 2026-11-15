"""The Codex adapter (module 9, phase 2 P2-1): `codex exec --json` headless, in the task worktree, under `srt`.

Codex's own sandbox runs each command under sandbox-exec, which fails inside srt (exit 71), so the adapter turns it off
and srt is the only layer. Codex reads the gateway key from the environment. Its own config and login are not used.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from ...errors import FactoryError
from ...interpolate import resolve
from ...prompt import build_prompt
from ...types import CheckResult, HelperPolicy
from . import sandbox
from .base import AttemptResult, Capabilities, HarnessConfig, TaskContext, WorkerHandle
from .runtime import (FORBIDDEN_ENV, attempt_folder, base_env, cache_env, declared_env, kill_group, read_text,
                      remove_attempt, secret_values, write_log, write_private)

# The variables the Codex harness reads from the environment. OPENAI_API_KEY is the gateway key.
CODEX_VARS = ("OPENAI_API_KEY", "OPENAI_BASE_URL")
# Untested: no run so far has used the public API, so this default has no evidence yet.
DEFAULT_BASE_URL = "https://api.openai.com/v1"
# --ignore-user-config drops the provider from config.toml, so the provider comes from per-key -c overrides.
PROVIDER = "custom"
# srt is the only sandbox layer, because codex's own sandbox-exec fails when nested inside srt.
SANDBOX_MODE = "danger-full-access"
# Codex's TLS needs this Mach lookup under srt. It is granted to Codex's settings only, not to the shared rules.
MACH_LOOKUP = ["com.apple.trustd.agent"]
# Captured output lives in the task folder: srt confines a sandboxed child's writes to the worktree and work/ (command.py).
EVENTS_FILE = "codex-events.jsonl"
STDERR_FILE = "codex-stderr.txt"
CODEX_HOME_DIR = "codex-home"


def codex_home(task_dir: Path) -> Path:
    """An empty folder for this task. Codex keeps no login or config here, so the key comes only from the environment."""
    return task_dir / CODEX_HOME_DIR


# ---- the srt settings file -----------------------------------------------------------------------------------------

def base_host(base_url: str) -> str:
    host = urlparse(base_url).hostname
    if not host:
        raise FactoryError("config.invalid", f"OPENAI_BASE_URL {base_url!r} has no host",
                           hint="set it to the gateway address, such as https://gateway.example/v1")
    return host


def srt_settings(worktree: Path, task_dir: Path, base_url: str, factory: Path | None = None) -> dict:
    """The shared srt rules, plus the gateway host as the one allowed domain and the Codex TLS grant."""
    doc = sandbox.srt_settings(worktree, task_dir, factory)
    doc["network"] = {"allowedDomains": [base_host(base_url)], "deniedDomains": [], "allowMachLookup": MACH_LOOKUP}
    return doc


def render_settings(worktree: Path, task_dir: Path, base_url: str, factory: Path | None = None) -> str:
    return json.dumps(srt_settings(worktree, task_dir, base_url, factory), indent=2)


def parse_settings_file(path: Path) -> dict:
    """Parse the settings file before a worker starts. A file srt cannot read as JSON would run the worker unsandboxed."""
    try:
        text = path.read_text()
    except OSError as e:
        raise FactoryError("sandbox.settings_unreadable", f"{path}: {e.strerror or e}") from e
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise FactoryError("sandbox.settings_unparseable", f"{path} is not JSON: {e}") from e
    fs = doc.get("filesystem") if isinstance(doc, dict) else None
    net = doc.get("network") if isinstance(doc, dict) else None
    problem = None
    if not isinstance(fs, dict) or not all(
            isinstance(fs.get(k), list) and all(isinstance(x, str) for x in fs[k])
            for k in ("denyRead", "allowRead", "allowWrite", "denyWrite")):
        problem = "filesystem needs denyRead, allowRead, allowWrite and denyWrite as lists of strings"
    elif not isinstance(net, dict) or not all(
            isinstance(net.get(k), list) and all(isinstance(x, str) for x in net[k])
            for k in ("allowedDomains", "deniedDomains")):
        problem = "network needs allowedDomains and deniedDomains as lists of strings"
    if problem:
        raise FactoryError("sandbox.settings_invalid", f"{path}: {problem}")
    return doc


# ---- the command line ----------------------------------------------------------------------------------------------

def resolve_binary(command: str, path: str | None) -> str | None:
    """srt reports a missing program as exit 127 from its shell, not as an error, so the adapter looks first."""
    if os.path.isabs(command):
        return command if os.access(command, os.X_OK) else None
    return shutil.which(command, path=path)


def codex_argv(binary: str, worktree: Path, *, model: str | None, base_url: str, helpers: HelperPolicy) -> list[str]:
    argv = [binary, "exec", "--json", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check",
            "-s", SANDBOX_MODE,
            "-c", f"model_provider={PROVIDER}",
            "-c", f"model_providers.{PROVIDER}.name=gateway",
            "-c", f"model_providers.{PROVIDER}.base_url={base_url}",
            "-c", f"model_providers.{PROVIDER}.env_key=OPENAI_API_KEY",
            "-c", f"model_providers.{PROVIDER}.wire_api=responses"]
    if helpers.mode == "off" or helpers.max <= 0:
        argv += ["--disable", "multi_agent"]  # subagents are on by default; the task allows none
    if model:
        argv += ["-m", model]
    return argv + ["-C", str(worktree), "-"]  # "-" reads the prompt from stdin


# ---- reading the event stream --------------------------------------------------------------------------------------

def parse_events(stdout: str) -> list[dict]:
    out = []
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            out.append(ev)
    return out


def plain_log(stdout: str) -> str:
    """worker.log text: agent messages, commands with their output, and errors, one per line."""
    lines: list[str] = []
    for raw in stdout.splitlines():
        try:
            ev = json.loads(raw)
        except ValueError:
            lines.append(raw)
            continue
        if not isinstance(ev, dict):
            continue
        kind, item = ev.get("type"), ev.get("item") or {}
        if kind == "item.completed" and item.get("type") == "agent_message":
            lines.append(str(item.get("text", "")))
        elif kind == "item.completed" and item.get("type") == "command_execution":
            lines.append(f"$ {item.get('command', '')}")
            if item.get("aggregated_output"):
                lines.append(str(item["aggregated_output"]).rstrip("\n"))
        elif kind == "error":
            lines.append(f"error: {ev.get('message', '')}")
        elif kind == "turn.failed":
            lines.append(f"turn failed: {_failure_message(ev)}")
    return "\n".join(lines)


def _failure_message(ev: dict) -> str:
    err = ev.get("error")
    return str(err.get("message", "")) if isinstance(err, dict) else str(err or "")


def _error_texts(events: list[dict]) -> list[str]:
    """Error events and failed turns only. An agent message or a command's output may quote a status code, so it is not read."""
    out = []
    for e in events:
        if e.get("type") == "error":
            out.append(str(e.get("message", "")))
        elif e.get("type") == "turn.failed":
            out.append(_failure_message(e))
    return out


def parse_usage(events: list[dict]) -> tuple[int | None, int | None]:
    """Tokens from the last turn.completed usage (module 9). Nothing reported is None, never 0."""
    usage = None
    for e in events:
        if e.get("type") == "turn.completed" and isinstance(e.get("usage"), dict):
            usage = e["usage"]
    if usage is None:
        return None, None
    ins, outs = usage.get("input_tokens"), usage.get("output_tokens")
    return (ins if isinstance(ins, int) else None), (outs if isinstance(outs, int) else None)


def error_kind(events: list[dict], stderr: str, returncode: int | None) -> str | None:
    """auth, model_not_found, rate_limit or crash. None when the turn completed."""
    types = {e.get("type") for e in events}
    if "turn.completed" in types and "turn.failed" not in types and returncode == 0:
        return None
    text = "\n".join([*_error_texts(events), stderr])
    if re.search(r"\b401\b|Unauthorized", text):
        return "auth"
    if re.search(r"\b403\b", text) and re.search(r"not available|model name is invalid", text):
        return "model_not_found"
    if re.search(r"\b429\b", text) or "rate limit" in text.lower():
        return "rate_limit"
    return "crash"


# ---- the adapter ---------------------------------------------------------------------------------------------------

class CodexAdapter:
    name = "codex"
    capabilities = Capabilities(subagents="native", usage=True)

    def __init__(self, environ: Mapping[str, str] | None = None):
        """environ is the machine's environment. It supplies the Codex variables the harness config does not declare."""
        self.environ: Mapping[str, str] = os.environ if environ is None else environ

    # environment ---------------------------------------------------------------------------------------------

    def _declared(self, conf: HarnessConfig) -> dict[str, str]:
        out = {k: resolve(str(v), self.environ, where=f"harnesses.codex.env.{k}") for k, v in conf.env.items()}
        for var in CODEX_VARS:
            if var not in out and var in self.environ:
                out[var] = self.environ[var]
        for var in FORBIDDEN_ENV:
            if out.get(var):
                raise FactoryError("config.invalid", f"harnesses.codex.env sets {var}; workers get no GitHub credentials",
                                   hint=f"remove {var} from the harness env; the engine makes every GitHub call")
        return out

    def _base_url(self, env: Mapping[str, str]) -> str:
        return env.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL

    def child_env(self, conf: HarnessConfig, task_dir: Path) -> dict[str, str]:
        env = base_env(self.environ)
        env.update(declared_env(self._declared(conf)))
        env["FACTORY_TASK_DIR"] = str(task_dir)
        env["CODEX_HOME"] = str(codex_home(task_dir))
        env.update(cache_env(task_dir))
        return env

    # doctor --------------------------------------------------------------------------------------------------

    def check(self, conf: HarnessConfig) -> CheckResult:
        """Binary, version, the gateway key and srt. Values are never printed, only the names of the variables."""
        binary = resolve_binary(conf.command, self.environ.get("PATH"))
        if binary is None:
            return CheckResult("codex", False, f"binary {conf.command!r} not found",
                               "install the Codex CLI, or set harnesses.codex.command to its path")
        r = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=60)
        lines = (r.stdout or r.stderr).strip().splitlines()
        version = lines[0] if lines else "unknown version"
        env = self._declared(conf)
        if not env.get("OPENAI_API_KEY"):
            return CheckResult("codex", False, f"{version}; config.no_credentials: OPENAI_API_KEY is not set",
                               "set OPENAI_API_KEY; a Codex login (auth.json) is not used")
        srt = sandbox.check_srt()
        if not srt.ok:
            return CheckResult("codex", False, f"{version}; {srt.detail}", srt.hint)
        base = self._base_url(env)
        return CheckResult("codex", True, f"{version}; credentials from OPENAI_API_KEY; base URL {base}", "")

    # worker lifecycle ---------------------------------------------------------------------------------------------

    def start(self, ctx: TaskContext, conf: HarnessConfig, log: Path) -> WorkerHandle:
        ctx.task_dir.mkdir(parents=True, exist_ok=True)
        bin_ = sandbox.require_srt()  # the worker never runs unsandboxed
        folder = attempt_folder(f"{ctx.task_id}-{ctx.attempt}")
        try:
            env = self._declared(conf)
            base_url = self._base_url(env)
            settings = folder / "srt-settings.json"
            write_private(settings, render_settings(ctx.worktree, ctx.task_dir, base_url))
            parse_settings_file(settings)  # before the worker starts
            prompt = folder / "prompt.md"
            write_private(prompt, build_prompt(ctx))
            model = ctx.model or conf.model
            binary = resolve_binary(conf.command, self.environ.get("PATH"))
            home = codex_home(ctx.task_dir)
            shutil.rmtree(home, ignore_errors=True)
            home.mkdir()
            proc = None
            if binary is not None:
                argv = codex_argv(binary, ctx.worktree, model=model, base_url=base_url, helpers=ctx.helpers)
                wrapped = sandbox.srt_command(bin_, settings, argv)
                proc = self._spawn(wrapped, ctx, conf, prompt)
        except BaseException:
            remove_attempt(folder)
            raise
        return WorkerHandle(ctx.task_id, ctx.attempt, {
            "proc": proc, "folder": folder, "log": log, "secrets": secret_values(env, []), "task_dir": ctx.task_dir,
            "artifact_name": ctx.artifact_name, "binary": conf.command,
            "stdout": ctx.task_dir / EVENTS_FILE, "stderr": ctx.task_dir / STDERR_FILE})

    def _spawn(self, wrapped: list[str], ctx: TaskContext, conf: HarnessConfig, prompt: Path) -> subprocess.Popen:
        """Starts the worker in its own session, so stop kills it and every helper it started."""
        out_path, err_path = ctx.task_dir / EVENTS_FILE, ctx.task_dir / STDERR_FILE
        with open(prompt) as stdin_f, open(out_path, "w") as out_f, open(err_path, "w") as err_f:
            return subprocess.Popen(wrapped, cwd=ctx.worktree, env=self.child_env(conf, ctx.task_dir), stdin=stdin_f,
                                    stdout=out_f, stderr=err_f, start_new_session=True)

    def wait(self, handle: WorkerHandle, timeout_s: int) -> AttemptResult:
        data = handle.data
        proc = data["proc"]
        if proc is None:
            write_log(data["log"], f"codex: binary {data['binary']!r} not found\n", data["secrets"])
            remove_attempt(data["folder"])
            return AttemptResult("failed", 127, None, None, None, [], "binary_missing")
        timed_out = False
        try:
            rc = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_group(proc)
            rc = proc.returncode
        stdout = read_text(data["stdout"])
        stderr = read_text(data["stderr"])
        write_log(data["log"], "\n".join(x for x in [plain_log(stdout), stderr] if x), data["secrets"])
        for key in ("stdout", "stderr"):
            data[key].unlink(missing_ok=True)
        remove_attempt(data["folder"])
        if timed_out:
            return AttemptResult("timeout", None, None, None, None, [], None)
        if data.get("stopped") or rc < 0:
            return AttemptResult("killed", None, None, None, None, [], None)
        events = parse_events(stdout)
        tokens_in, tokens_out = parse_usage(events)
        kind = error_kind(events, stderr, rc)
        artifact = data["task_dir"] / data["artifact_name"]
        return AttemptResult("ok" if kind is None else "failed", rc, artifact if artifact.is_file() else None,
                             tokens_in, tokens_out, [], kind)  # type: ignore[arg-type]

    def stop(self, handle: WorkerHandle) -> None:
        proc = handle.data.get("proc")
        if proc is not None and proc.poll() is None:
            kill_group(proc)
        handle.data["stopped"] = True
