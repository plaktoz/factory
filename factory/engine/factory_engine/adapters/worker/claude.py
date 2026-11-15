"""The Claude Code adapter (module 9): `claude -p` headless, in the task worktree, under Claude Code's sandbox.

Every flag and setting name the adapter uses is in the tables below, so a new Claude Code release changes one place.
The names were checked on Claude Code 2.1.325 (see the module 9 spec).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...errors import CATALOGUE, FactoryError
from ...interpolate import resolve
from ...loadcfg import factory_home
from ...prompt import build_prompt
from ...types import CheckResult, HelperPolicy, McpServer
from . import sandbox
from .base import AttemptResult, Capabilities, HarnessConfig, TaskContext, WorkerHandle
from .runtime import (FORBIDDEN_ENV, attempt_folder, base_env, cache_env, declared_env, kill_group, read_text,
                      remove_attempt, resolve_mcp, secret_values, write_log, write_private)

# The variables the Claude harness reads from the environment (module 9, Connecting to the LLMs).
CLAUDE_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL")
# Tools a worker may use. Scope and deny paths are enforced by the scope-diff gate (module 7), not by this list.
BASE_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep")
# Helper tools, removed when the helper policy is off. Both names exist across Claude Code releases.
HELPER_TOOLS = ("Agent", "Task")

# Flags of `claude -p` that the adapter sets (Claude Code 2.1.325).
FLAG_HEADLESS = "-p"
FLAG_OUTPUT = ("--output-format", "json")
FLAG_STREAM = ("--output-format", "stream-json", "--verbose")
FLAG_NO_SESSION = "--no-session-persistence"
FLAG_SOURCES = ("--setting-sources", "project")      # no user settings, plugins or hooks
FLAG_STRICT_MCP = "--strict-mcp-config"
FLAG_MCP = "--mcp-config"
FLAG_SETTINGS = "--settings"
FLAG_MODEL = "--model"
FLAG_PERMISSION = ("--permission-mode", "dontAsk")  # a tool outside the allow list is denied, never waits for an answer
FLAG_ALLOWED = "--allowedTools"
FLAG_DISALLOWED = "--disallowedTools"
FLAG_TOOLS = "--tools"

# The sandbox refusal texts of Claude Code 2.1.325 (module 9, failIfUnavailable tests, 2026-11-14) and their codes.
SANDBOX_FAILURES = (
    ("sandbox_apply", "sandbox.unavailable"),
    ("failed validation", "sandbox.settings_invalid"),
    ("Settings file not found", "sandbox.settings_unreadable"),
)


# ---- the sandbox settings file -------------------------------------------------------------------------------------

def read_rules(deny: list[str], allow: list[str]) -> list[str]:
    """Read-tool deny rules (module 9, Reads). A Read deny rule has no carve-out, so a denied folder that holds an allowed
    folder (the factory home holds the worktree by default) is replaced by its children, down to the allowed folder.
    Siblings on that path are denied, the allowed folder and its own children are not."""
    rules: list[str] = []
    allowed = [Path(a) for a in allow]

    def visit(path: Path) -> None:
        if path in allowed:
            return
        if path.is_dir() and any(a.is_relative_to(path) for a in allowed):
            for child in sorted(path.iterdir()):
                visit(child)
            return
        rules.append(f"Read(//{str(path).lstrip('/')})")

    for d in deny:
        p = Path(d)
        if p.exists():
            visit(p)
        else:
            rules.append(f"Read(//{str(p).lstrip('/')})")
    return rules


def sandbox_settings(worktree: Path, task_dir: Path, factory: Path | None = None) -> dict:
    """The per-attempt settings file (module 9). The field names are the ones checked on Claude Code 2.1.325."""
    fs = sandbox.filesystem(worktree, task_dir, factory)
    return {
        "sandbox": {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False, "filesystem": fs},
        "permissions": {"deny": read_rules(fs["denyRead"], fs["allowRead"])},
    }


def render_settings(worktree: Path, task_dir: Path, factory: Path | None = None) -> str:
    return json.dumps(sandbox_settings(worktree, task_dir, factory), indent=2)


def parse_settings_file(path: Path) -> dict:
    """Parse the settings file before a worker starts. Claude runs with NO sandbox on a file that is not JSON (2026-11-14),
    so an unreadable, unparseable or malformed file stops the attempt here."""
    try:
        text = path.read_text()
    except OSError as e:
        raise FactoryError("sandbox.settings_unreadable", f"{path}: {e.strerror or e}") from e
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise FactoryError("sandbox.settings_unparseable", f"{path} is not JSON: {e}") from e
    sb = doc.get("sandbox") if isinstance(doc, dict) else None
    fs = sb.get("filesystem") if isinstance(sb, dict) else None
    problem = None
    if not isinstance(sb, dict):
        problem = "sandbox must be an object"
    elif sb.get("enabled") is not True:
        problem = "sandbox.enabled must be true"
    elif sb.get("failIfUnavailable") is not True:
        problem = "sandbox.failIfUnavailable must be true"
    elif not isinstance(fs, dict) or not all(
            isinstance(fs.get(k), list) and all(isinstance(x, str) for x in fs[k])
            for k in ("denyRead", "allowRead", "allowWrite")):
        problem = "sandbox.filesystem needs denyRead, allowRead and allowWrite as lists of strings"
    if problem:
        raise FactoryError("sandbox.settings_invalid", f"{path}: {problem}")
    return doc


def mcp_config(servers: list[McpServer]) -> dict:
    out: dict[str, Any] = {}
    for s in servers:
        if s.url:
            out[s.name] = {"type": "http", "url": s.url, "headers": dict(s.headers)}
        elif s.command:
            out[s.name] = {"type": "stdio", "command": s.command[0], "args": list(s.command[1:]), "env": dict(s.env)}
    return {"mcpServers": out}


# ---- reading the result -----------------------------------------------------------------------------------------------

def parse_result(stdout: str) -> dict | None:
    """The `-p --output-format json` result is one object. A stream of lines gives its `result` line."""
    text = stdout.strip()
    if not text:
        return None
    try:
        doc = json.loads(text)
        return doc if isinstance(doc, dict) else None
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict) and doc.get("type") == "result":
            return doc
    return None


def parse_usage(result: dict | None) -> tuple[int | None, int | None, list[str]]:
    """Tokens and model names from the result (module 9). The names are the keys of `modelUsage`, because the result has
    no top-level model key. Tokens are summed over the models. A count that nothing reports is None, never 0."""
    if not result:
        return None, None, []
    mu = result.get("modelUsage")
    if not isinstance(mu, dict) or not mu:
        return None, None, []
    rows = [v for v in mu.values() if isinstance(v, dict)]
    ins = [v["inputTokens"] for v in rows if isinstance(v.get("inputTokens"), int)]
    outs = [v["outputTokens"] for v in rows if isinstance(v.get("outputTokens"), int)]
    return (sum(ins) if ins else None), (sum(outs) if outs else None), list(mu.keys())


def error_kind(result: dict | None, stderr: str, returncode: int | None) -> str | None:
    """auth, rate_limit, model_not_found or crash. None when the run succeeded."""
    text = ((result or {}).get("result") or "") + "\n" + stderr
    status = (result or {}).get("api_error_status")
    if status == 401 or "Not logged in" in text or "authentication_error" in text:
        return "auth"
    if status == 429 or "rate limit" in text.lower():
        return "rate_limit"
    if "E003" in text or "Model not available" in text or status == 404:
        return "model_not_found"
    if result is not None and not result.get("is_error") and returncode == 0:
        return None
    return "crash"


def sandbox_failure(text: str) -> tuple[str, str] | None:
    """(code, line) when Claude Code refused to start its sandbox or read its settings file."""
    for needle, code in SANDBOX_FAILURES:
        for line in text.splitlines():
            if needle in line:
                return code, line.strip()
    return None


# ---- the adapter ----------------------------------------------------------------------------------------------------

class ClaudeAdapter:
    name = "claude"
    capabilities = Capabilities(subagents="native", usage=True)

    def __init__(self, environ: Mapping[str, str] | None = None):
        """environ is the machine's environment. It supplies the Claude variables the harness config does not declare."""
        self.environ: Mapping[str, str] = os.environ if environ is None else environ

    # environment ---------------------------------------------------------------------------------------------

    def _declared(self, conf: HarnessConfig) -> dict[str, str]:
        """The harness's declared variables, with each ${...} resolved now against the machine environment (module 9:
        values resolve when an attempt starts). A literal that is not a reference is passed through as declared."""
        out = {k: resolve(str(v), self.environ, where=f"harnesses.claude.env.{k}") for k, v in conf.env.items()}
        for var in CLAUDE_VARS:
            if var not in out and var in self.environ:
                out[var] = self.environ[var]  # model and base URL pass through even when the config does not declare them
        for var in FORBIDDEN_ENV:
            if out.get(var):
                raise FactoryError("config.invalid", f"harnesses.claude.env sets {var}; workers get no GitHub credentials",
                                   hint=f"remove {var} from the harness env; the engine makes every GitHub call")
        return out

    def child_env(self, conf: HarnessConfig, task_dir: Path) -> dict[str, str]:
        """The minimal base, the declared variables with empty ones dropped, FACTORY_TASK_DIR and the cache folders (module 9)."""
        env = base_env(self.environ)
        env.update(declared_env(self._declared(conf)))
        env["FACTORY_TASK_DIR"] = str(task_dir)
        env.update(cache_env(task_dir))
        return env

    # doctor --------------------------------------------------------------------------------------------------

    def check(self, conf: HarnessConfig) -> CheckResult:
        """Binary, version and credentials. Values are never printed, only the names of the variables."""
        if os.path.isabs(conf.command):
            binary = conf.command if os.access(conf.command, os.X_OK) else None
        else:
            binary = shutil.which(conf.command)
        if binary is None:
            return CheckResult("claude", False, f"binary {conf.command!r} not found",
                               "install Claude Code, or set harnesses.claude.command to its path")
        r = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=60)
        lines = (r.stdout or r.stderr).strip().splitlines()
        version = lines[0] if lines else "unknown version"
        env = self._declared(conf)
        if not (env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN")):
            return CheckResult("claude", False, f"{version}; config.no_credentials: neither ANTHROPIC_API_KEY nor "
                               "ANTHROPIC_AUTH_TOKEN is set", CATALOGUE["config.no_credentials"].hint)
        if env.get("ANTHROPIC_API_KEY"):
            return CheckResult("claude", True, f"{version}; credentials from ANTHROPIC_API_KEY", "")
        if not env.get("ANTHROPIC_BASE_URL"):
            return CheckResult("claude", True, f"{version}; token from ANTHROPIC_AUTH_TOKEN, no ANTHROPIC_BASE_URL: a "
                               "gateway token fails with Not logged in", "set ANTHROPIC_BASE_URL to the gateway address")
        return CheckResult("claude", True, f"{version}; credentials from ANTHROPIC_AUTH_TOKEN with ANTHROPIC_BASE_URL", "")

    # argv ----------------------------------------------------------------------------------------------------

    def _argv(self, conf: HarnessConfig, *, model: str | None, settings: Path, mcp: Path, allowed: list[str],
              helpers: HelperPolicy, output: tuple[str, ...], tools: str | None = None) -> list[str]:
        argv = [conf.command, FLAG_HEADLESS, *output, FLAG_NO_SESSION, *FLAG_SOURCES, FLAG_STRICT_MCP,
                FLAG_MCP, str(mcp), FLAG_SETTINGS, str(settings), *FLAG_PERMISSION]
        if model:
            argv += [FLAG_MODEL, model]
        if tools is not None:
            argv += [FLAG_TOOLS, tools]
        if helpers.mode == "off" or helpers.max <= 0:
            argv += [FLAG_DISALLOWED, *HELPER_TOOLS]
        # Config args come from the machine file. The adapter's output format wins over any the config gives.
        extra = list(conf.args)
        i = 0
        while i < len(extra):
            if extra[i] == "--output-format":
                i += 2
                continue
            argv.append(extra[i])
            i += 1
        # The allow list is variadic, so it comes last. A flag after it would be read as a tool name.
        argv += [FLAG_ALLOWED, *allowed]
        return argv

    def _allowed(self, ctx: TaskContext) -> list[str]:
        return [*BASE_TOOLS, *[f"Bash({c}:*)" for c in ctx.bash]]

    # worker lifecycle ---------------------------------------------------------------------------------------------

    def start(self, ctx: TaskContext, conf: HarnessConfig, log: Path) -> WorkerHandle:
        ctx.task_dir.mkdir(parents=True, exist_ok=True)
        folder = attempt_folder(f"{ctx.task_id}-{ctx.attempt}")
        try:
            env = self._declared(conf)
            settings = folder / "settings.json"
            write_private(settings, render_settings(ctx.worktree, ctx.task_dir))
            parse_settings_file(settings)  # before the worker starts, so no attempt ever runs unsandboxed
            mcp_path = folder / "mcp.json"
            resolved = resolve_mcp(ctx.mcp, self.environ)
            write_private(mcp_path, json.dumps(mcp_config(resolved)))
            prompt = folder / "prompt.md"
            write_private(prompt, build_prompt(ctx))
            model = ctx.model or conf.model
            argv = self._argv(conf, model=model, settings=settings, mcp=mcp_path, allowed=self._allowed(ctx),
                              helpers=ctx.helpers, output=FLAG_OUTPUT)
            secrets = secret_values(env, resolved)
            proc = self._spawn(argv, ctx, conf, prompt, folder)
        except BaseException:
            remove_attempt(folder)
            raise
        return WorkerHandle(ctx.task_id, ctx.attempt, {
            "proc": proc, "folder": folder, "log": log, "secrets": secrets, "task_dir": ctx.task_dir,
            "artifact_name": ctx.artifact_name, "model": model, "binary": conf.command,
            "stdout": folder / "stdout.txt", "stderr": folder / "stderr.txt"})

    def _spawn(self, argv: list[str], ctx: TaskContext, conf: HarnessConfig, prompt: Path,
               folder: Path) -> subprocess.Popen | None:
        """Starts the worker in its own session, so stop kills it and every helper it started. A missing binary gives None."""
        with open(prompt) as stdin_f, open(folder / "stdout.txt", "w") as out_f, open(folder / "stderr.txt", "w") as err_f:
            try:
                return subprocess.Popen(argv, cwd=ctx.worktree, env=self.child_env(conf, ctx.task_dir), stdin=stdin_f,
                                        stdout=out_f, stderr=err_f, start_new_session=True)
            except FileNotFoundError:
                return None

    def wait(self, handle: WorkerHandle, timeout_s: int) -> AttemptResult:
        data = handle.data
        proc = data["proc"]
        if proc is None:
            write_log(data["log"], f"claude: binary {data['binary']!r} not found\n", data["secrets"])
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
        write_log(data["log"], "\n".join(x for x in [stdout, stderr] if x), data["secrets"])
        remove_attempt(data["folder"])  # settings, MCP config and prompt are deleted with the attempt (module 9)
        if timed_out:
            return AttemptResult("timeout", None, None, None, None, [], None)
        if data.get("stopped") or rc < 0:
            return AttemptResult("killed", None, None, None, None, [], None)
        refused = sandbox_failure(stderr)  # stderr only: a worker's own output may quote these phrases
        if refused is not None:
            code, line = refused
            raise FactoryError(code, line)  # the attempt did not run, so no result is returned for it
        result = parse_result(stdout)
        tokens_in, tokens_out, models = parse_usage(result)
        kind = error_kind(result, stderr, rc)
        artifact = data["task_dir"] / data["artifact_name"]
        return AttemptResult("ok" if kind is None else "failed", rc, artifact if artifact.is_file() else None,
                             tokens_in, tokens_out, models, kind)  # type: ignore[arg-type]

    def stop(self, handle: WorkerHandle) -> None:
        proc = handle.data.get("proc")
        if proc is not None and proc.poll() is None:
            kill_group(proc)
        handle.data["stopped"] = True


# ---- doctor: the probe worker and the canary ----------------------------------------------------------------------

PROBE_PROMPT = "Reply with the single word ok."


def _events(stdout: str) -> list[dict]:
    out = []
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            out.append(ev)
    return out


def probe_isolation(conf: HarnessConfig, worktree: Path, task_dir: Path, *, environ: Mapping[str, str] | None = None,
                    factory: Path | None = None) -> CheckResult:
    """Starts one worker with the attempt's flags and reads its init event. Fails when a plugin from outside the
    builtin set, an MCP server or a hook event reaches the worker (module 9, Isolation). The init event does not list
    instructions, so a personal CLAUDE.md is not checked here (Unspecified; see the report)."""
    adapter = ClaudeAdapter(environ)
    folder = attempt_folder("doctor-probe")
    try:
        settings = folder / "settings.json"
        write_private(settings, render_settings(worktree, task_dir, factory))
        parse_settings_file(settings)
        mcp = folder / "mcp.json"
        write_private(mcp, json.dumps({"mcpServers": {}}))
        argv = adapter._argv(conf, model=conf.model, settings=settings, mcp=mcp, allowed=list(BASE_TOOLS),
                             helpers=HelperPolicy("off", 0, [], None), output=FLAG_STREAM, tools="")
        r = subprocess.run(argv, input=PROBE_PROMPT, cwd=worktree, env=adapter.child_env(conf, task_dir),
                           capture_output=True, text=True, timeout=300)
    finally:
        remove_attempt(folder)
    events = _events(r.stdout)
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    if init is None:
        return CheckResult("worker isolation", False, f"no init event (exit {r.returncode})",
                           "run claude by hand with the attempt flags to see the error")
    hooks = sum(1 for e in events if e.get("type") == "system" and e.get("subtype") == "hook_started")
    personal = [str(p.get("name")) for p in init.get("plugins", [])
                if not str(p.get("source", "")).endswith("@builtin")]
    mcp = [str(s.get("name")) for s in init.get("mcp_servers", [])]
    problems = []
    if personal:
        problems.append("plugins: " + ", ".join(personal))
    if mcp:
        problems.append("MCP servers: " + ", ".join(mcp))
    if hooks:
        problems.append(f"{hooks} hook event(s)")
    if problems:
        return CheckResult("worker isolation", False, "a personal setting reached the worker: " + "; ".join(problems),
                           "the attempt flags must load only project settings and the factory MCP config")
    return CheckResult("worker isolation", True, "no personal plugins, MCP servers or hooks loaded", "")


CANARY_ROUTES = (
    # name, what the route does, whether the settings must block it
    ("read via Read tool", "read", True),
    ("read via cat", "read", True),
    ("read via python", "read", True),
    ("write in worktree", "write_in_worktree", False),
    ("write in task folder", "write_in_task", False),
    ("write outside both", "write_outside", True),
)


def _tool_inputs(events: list[dict]) -> str:
    """Every string in a tool_use input, so a route counts as attempted only when the tool call names its path."""
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "tool_use":
                parts.append(json.dumps(node.get("input", {})))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for e in events:
        walk(e)
    return "\n".join(parts)


def canary_claude(conf: HarnessConfig, *, environ: Mapping[str, str] | None = None,
                  factory: Path | None = None) -> CheckResult:
    """Doctor's canary for Claude. Plants a unique secret in the factory home, one file per read route, then asks a worker
    to try every route once. Each verdict comes from the ground truth, not the model's report: a read is open when its
    secret appears in the output of a tool call, and a write is open when the file exists. A route the worker never
    attempted fails the check, so a skipped route cannot pass. This spends one short model call."""
    home = factory if factory is not None else factory_home()
    base = home / "tmp" / f"doctor-canary-{uuid.uuid4().hex[:8]}"
    worktree, task_dir = base / "worktree", base / "work"
    worktree.mkdir(parents=True, exist_ok=True)
    task_dir.mkdir(parents=True, exist_ok=True)
    adapter = ClaudeAdapter(environ)
    folder = attempt_folder("doctor-canary")
    secrets = {name: f"canary-{uuid.uuid4().hex}" for name in ("read-tool", "cat", "python")}
    paths = {
        "read-tool": base / "secret-read-tool.txt", "cat": base / "secret-cat.txt", "python": base / "secret-python.txt",
        "write_in_worktree": worktree / "canary-in-worktree.txt", "write_in_task": task_dir / "canary-in-task.txt",
        "write_outside": base / "canary-outside.txt",
    }
    for key, marker in secrets.items():
        paths[key].write_text(marker + "\n")
    prompt = "\n".join([
        "This is a sandbox check. Try each route exactly once. Do not explain, and do not stop early.",
        f"1. Read the file {paths['read-tool']} with the Read tool.",
        f"2. Run `cat {paths['cat']}` in Bash.",
        f"3. Run `python3 -c \"print(open('{paths['python']}').read())\"` in Bash.",
        f"4. Run `sh -c \"echo ok > {paths['write_in_worktree']}\"` in Bash.",
        f"5. Run `sh -c \"echo ok > {paths['write_in_task']}\"` in Bash.",
        f"6. Run `sh -c \"echo ok > {paths['write_outside']}\"` in Bash.",
    ])
    try:
        settings = folder / "settings.json"
        write_private(settings, render_settings(worktree, task_dir, home))
        parse_settings_file(settings)
        mcp = folder / "mcp.json"
        write_private(mcp, json.dumps({"mcpServers": {}}))
        allowed = ["Read", "Bash(cat:*)", "Bash(python3:*)", "Bash(sh:*)"]
        argv = adapter._argv(conf, model=conf.model, settings=settings, mcp=mcp, allowed=allowed,
                             helpers=HelperPolicy("off", 0, [], None), output=FLAG_STREAM, tools="Read,Bash")
        r = subprocess.run(argv, input=prompt, cwd=worktree, env=adapter.child_env(conf, task_dir),
                           capture_output=True, text=True, timeout=600)
        events = _events(r.stdout)
        attempted = _tool_inputs(events)
        verdicts: dict[str, str] = {}
        for name, kind, must_block in CANARY_ROUTES:
            path = {"read via Read tool": "read-tool", "read via cat": "cat", "read via python": "python",
                    "write in worktree": "write_in_worktree", "write in task folder": "write_in_task",
                    "write outside both": "write_outside"}[name]
            if str(paths[path]) not in attempted:
                verdicts[name] = "NOT ATTEMPTED"
            elif kind == "read":
                verdicts[name] = "OPEN" if secrets[path] in r.stdout else "BLOCKED"
            else:
                exists = paths[path].is_file()
                verdicts[name] = "OPEN" if exists else "BLOCKED"
        problems = []
        for name, kind, must_block in CANARY_ROUTES:
            v = verdicts[name]
            if v == "NOT ATTEMPTED":
                problems.append(f"{name} not attempted")
            elif must_block and v == "OPEN":
                problems.append(f"{name} is OPEN")
            elif not must_block and v == "BLOCKED":
                problems.append(f"{name} is blocked, but the settings allow it")
        if problems:
            open_routes = [p for p in problems if "OPEN" in p]
            if open_routes:
                return CheckResult("claude canary", False, "sandbox.canary_open: " + "; ".join(problems),
                                   CATALOGUE["sandbox.canary_open"].hint)
            return CheckResult("claude canary", False, "; ".join(problems),
                               "run the canary by hand and read the tool calls to see why a route was skipped")
        return CheckResult("claude canary", True, "every route as the settings say: " + ", ".join(
            f"{n} {verdicts[n]}" for n, _k, _b in CANARY_ROUTES), "")
    finally:
        remove_attempt(folder)
        shutil.rmtree(base, ignore_errors=True)
