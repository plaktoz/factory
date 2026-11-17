"""Gates (module 8): run a stage's gates in order, stop at the first failure, and return each result with its output tail.

A gate is a command (`cmd`), a named check (`check`) or an artifact schema (`schema`). A command runs through
CommandAdapter (module 9), under srt with the worker's read and write rules. Its exit code decides the gate:
0 passes, anything else fails it. A missing binary or a sandbox that cannot start is a task error, not a failure.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .checks import CHECKS, resolve
from .errors import FactoryError
from .state import append_event
from .types import GateContext, GateResult, GateSpec
from .validate import SCHEMA_DIR, validate

TAIL_LINES = 200

# (argv, ctx) -> (exit code, combined output). The default runs CommandAdapter under srt.
CommandRunner = Callable[[list[str], GateContext], tuple[int, str]]


@dataclass
class TestReport:
    total: int
    failed: list[str] = field(default_factory=list)


def known_checks() -> set[str]:
    return set(CHECKS)


def tail(text: str, lines: int = TAIL_LINES) -> str:
    return "\n".join(text.splitlines()[-lines:])


def parse_junit(paths: list[Path]) -> TestReport:
    """Count the JUnit test cases and name the failed ones. A missing or unreadable file contributes nothing."""
    total = 0
    failed: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        for case in root.iter("testcase"):
            total += 1
            if case.find("failure") is not None or case.find("error") is not None:
                failed.append(case.get("name", ""))
    return TestReport(total=total, failed=failed)


GATE_TIMEOUT_SECONDS = 30 * 60


def _adapter_runner(cmd: list[str], ctx: GateContext) -> tuple[int, str]:
    """Run a gate command through CommandAdapter under srt, in the worktree (module 8, Gate commands run sandboxed).

    The adapter's wait returns no exit code for a command, so this reads the exit code from the adapter's
    AttemptResult and the output from the worker log it writes. srt starts the command through a shell, so a missing
    binary reaches the adapter as exit 127 with "command not found", not as a failed start. That case raises
    FileNotFoundError, which _cmd_gate turns into gate.command_missing (a task error, not a failed gate)."""
    from .adapters.worker.base import HarnessConfig, TaskContext
    from .adapters.worker.command import CommandAdapter

    task_dir = ctx.task_dir or ctx.worktree
    task_dir.mkdir(parents=True, exist_ok=True)
    adapter = CommandAdapter()
    gate_ctx = TaskContext(
        run_id=ctx.run.run_id, task_id=ctx.task_id or "gate", stage=ctx.stage, attempt=1, skill=None,
        request=ctx.run.request, worktree=ctx.worktree, task_dir=task_dir, scope=list(ctx.scope),
        deny=list(ctx.deny), helpers=None, feedback=[], notes=[], progress=None, output_schema=None, model=None,
        mcp=[], practices=[], cmd=list(cmd))
    log = task_dir / "gate-command.log"
    handle = adapter.start(gate_ctx, HarnessConfig(adapter.name, None, [], {}), log)
    outcome = adapter.wait(handle, GATE_TIMEOUT_SECONDS)
    output = log.read_text(errors="replace") if log.is_file() else ""
    if outcome.error_kind == "binary_missing" or (outcome.exit_code == 127 and "command not found" in output):
        raise FileNotFoundError(2, "no such binary", cmd[0])
    code = outcome.exit_code if outcome.exit_code is not None else 1
    return code, output


_runner: CommandRunner = _adapter_runner


@contextmanager
def use_command_runner(runner: CommandRunner) -> Iterator[None]:
    """Run cmd gates through `runner` inside the block. The default is CommandAdapter under srt; tests pass a stub."""
    global _runner
    previous, _runner = _runner, runner
    try:
        yield
    finally:
        _runner = previous


def run_gates(gates: list[GateSpec], ctx: GateContext) -> list[GateResult]:
    """Run the gates in order and stop at the first failure. The last result is the failing one when there is one."""
    results: list[GateResult] = []
    for spec in gates:
        result = _run_one(spec, ctx)
        results.append(result)
        if not result.passed:
            break
    return results


def record_gates(run_dir: Path, results: list[GateResult]) -> None:
    """Append gate_passed or gate_failed for each result, in the order the gates ran.

    The output tail stays out of events.jsonl: it can hold a secret the worker printed (module 9 masks it only in
    the feedback record and the worker log). The feedback record carries the tail for the worker."""
    for r in results:
        event = "gate_passed" if r.passed else "gate_failed"
        exit_code = r.details.get("exit_code")
        append_event(run_dir, event, gate=r.gate, code=r.code, exit_code=exit_code)


def _run_one(spec: GateSpec, ctx: GateContext) -> GateResult:
    if spec.kind == "cmd":
        return _cmd_gate(spec, ctx)
    if spec.kind == "check":
        if not spec.check:
            raise FactoryError("config.invalid", "a check gate needs a check name",
                               hint="write the gate as {check: scope-diff}")
        return resolve(spec.check)(spec, ctx)
    return _schema_gate(spec, ctx)


def _cmd_gate(spec: GateSpec, ctx: GateContext) -> GateResult:
    if not spec.cmd:
        raise FactoryError("config.invalid", "a cmd gate needs a non-empty command list",
                           hint="write the gate as {cmd: [make, test]}, a list, never a string")
    try:
        code, output = _runner(spec.cmd, ctx)
    except FileNotFoundError as e:
        raise FactoryError("gate.command_missing", f"{spec.cmd[0]}: {e}") from e
    return cmd_gate_result(spec.cmd, code, output, ctx)


def _cmd_name(cmd: list[str]) -> str:
    return "cmd: [" + ", ".join(cmd) + "]"


def gate_name(spec: GateSpec) -> str:
    """The id of a gate: the name its results and gate events carry, and the one `factory skip --gate` takes.

    A cmd gate is `cmd: [make, lint]`, a schema gate is `schema: stage-report`, and a check gate is its check name."""
    if spec.kind == "cmd":
        return _cmd_name(spec.cmd or [])
    if spec.kind == "schema":
        return f"schema: {spec.schema}"
    return spec.check or ""


def cmd_gate_result(cmd: list[str], exit_code: int, output: str, ctx: GateContext) -> GateResult:
    """The result of a command that ran, from its exit code and output (module 8, class table).

    Used for a cmd gate and for a failed cmd task: the spec treats a non-zero exit from a command task as a gate
    failure, so 6B passes its command's result here and gets the same rework feedback. Zero passes. Any other exit
    fails with the output tail, the failing test names from the task's JUnit report (ctx.artifact), and the files
    git reports as changed."""
    name = _cmd_name(cmd)
    if exit_code == 0:
        return GateResult(passed=True, gate=name, code="ok", output_tail="", details={"exit_code": 0})
    # The changed files come from git (module 7), read through the same function its scope check uses.
    from .gitops import changed_files

    failed = parse_junit([ctx.artifact] if ctx.artifact else []).failed
    changed = changed_files(ctx.worktree, ctx.task_base) if ctx.task_base else []
    return GateResult(passed=False, gate=name, code="gate.exit_code", output_tail=tail(output),
                      details={"exit_code": exit_code, "failed_tests": failed, "changed_files": changed})


def _schema_gate(spec: GateSpec, ctx: GateContext) -> GateResult:
    if not spec.schema:
        raise FactoryError("config.invalid", "a schema gate needs a schema name",
                           hint="write the gate as {schema: stage-report}")
    name = gate_name(spec)
    if not (SCHEMA_DIR / f"{spec.schema}.schema.json").is_file():
        raise FactoryError("config.invalid", f"no schema named {spec.schema!r} in {SCHEMA_DIR}",
                           hint="the schema must be in factory/schemas/")
    if ctx.artifact is None or not ctx.artifact.is_file():
        return GateResult(passed=False, gate=name, code="gate.no_artifact",
                          output_tail="the attempt wrote no artifact", details={})
    try:
        doc = json.loads(ctx.artifact.read_text())
    except (OSError, ValueError) as e:
        return GateResult(passed=False, gate=name, code="gate.schema",
                          output_tail=f"the artifact is not JSON: {e}", details={})
    try:
        validate(doc, spec.schema, file=str(ctx.artifact))
    except FactoryError as e:
        return GateResult(passed=False, gate=name, code="gate.schema", output_tail=e.message, details={})
    return GateResult(passed=True, gate=name, code="ok", output_tail="", details={})


# A check the spec does not say how to run fails fast, so a gate never passes an artifact it cannot judge.

def _unbuilt(check: str, schema: str) -> FactoryError:
    return FactoryError("config.invalid", f"check {check!r} reads {schema}, but the spec does not say how to run it",
                        hint=f"define how {check} matches a claim to a source before a gate uses it")


def _stage_artifacts(ctx: GateContext) -> list[Path]:
    """The artifact of the task being gated, or the JSON files in every task folder of the stage's latest visit."""
    if ctx.artifact is not None:
        return [ctx.artifact]
    run_dir = Path(ctx.run.paths.get("run_dir", ""))
    visits = [s for s in ctx.run.stages if s.id == ctx.stage]
    if not visits:
        return []
    found: list[Path] = []
    for task_id in visits[-1].tasks:
        found += sorted(p for p in (run_dir / "tasks" / task_id).glob("*.json")
                        if p.name not in ("task.json", "progress.json") and not p.name.startswith("ledger"))
    return found


def _read_artifacts(ctx: GateContext, schema: str, gate: str) -> tuple[list[tuple[Path, dict]], GateResult | None]:
    docs: list[tuple[Path, dict]] = []
    paths = _stage_artifacts(ctx)
    if not paths:
        return [], GateResult(passed=False, gate=gate, code="gate.no_artifact",
                              output_tail="the stage wrote no artifact", details={})
    for path in paths:
        try:
            doc = json.loads(path.read_text())
            validate(doc, schema, file=str(path))
        except (OSError, ValueError) as e:
            return [], GateResult(passed=False, gate=gate, code="gate.schema",
                                  output_tail=f"{path.name} is not JSON: {e}", details={})
        except FactoryError as e:
            return [], GateResult(passed=False, gate=gate, code="gate.schema", output_tail=e.message, details={})
        docs.append((path, doc))
    return docs, None


# The spec does not say what "blocking" means. The owner accepted: a finding with severity medium or high blocks.
BLOCKING_SEVERITIES = ("medium", "high")


def check_findings(spec: GateSpec, ctx: GateContext) -> GateResult:
    """no-blocking-findings: every review-findings artifact of the stage has no finding of medium or high severity."""
    gate = "no-blocking-findings"
    docs, bad = _read_artifacts(ctx, "review-findings", gate)
    if bad:
        return bad
    blocking = [f for _, d in docs for f in d["findings"] if f["severity"] in BLOCKING_SEVERITIES]
    if blocking:
        tail_text = "\n".join(f"{f['severity']} {f['file']}:{f['line']} {f['rule']}" for f in blocking)
        return GateResult(passed=False, gate=gate, code="gate.blocking_findings", output_tail=tail(tail_text),
                          details={"blocking": len(blocking)})
    return GateResult(passed=True, gate=gate, code="ok", output_tail="", details={"blocking": 0})


def check_evidence(spec: GateSpec, ctx: GateContext) -> GateResult:
    """evidence-cites-code: the stage report has at least one claim, and every claim cites a line that exists in a
    file of the worktree. It checks that the cited code exists, not that it is the cause (phase 2 item 3)."""
    gate = "evidence-cites-code"
    docs, bad = _read_artifacts(ctx, "stage-report", gate)
    if bad:
        return bad
    claims = [c for _, d in docs for c in d.get("claims", [])]
    problems = [] if claims else ["the report has no claims that cite code"]
    root = ctx.worktree.resolve()
    for c in claims:
        target = (ctx.worktree / c["file"]).resolve()
        if root not in target.parents or not target.is_file():
            problems.append(f"{c['file']}:{c['line']}: no such file in the worktree")
        elif c["line"] > len(target.read_text(errors="replace").splitlines()):
            problems.append(f"{c['file']}:{c['line']}: the file has fewer lines")
    if problems:
        return GateResult(passed=False, gate=gate, code="gate.evidence", output_tail=tail("\n".join(problems)),
                          details={"problems": len(problems)})
    return GateResult(passed=True, gate=gate, code="ok", output_tail="", details={"claims": len(claims)})


def write_test_report(junit: list[Path], out: Path) -> Path:
    """Write the test-report artifact a `{schema: test-report}` gate reads, from the tasks' JUnit files."""
    report = parse_junit(junit)
    out.write_text(json.dumps({"schema_version": 1, "total": report.total, "failed": report.failed}, indent=2) + "\n")
    return out


def check_sources(spec: GateSpec, ctx: GateContext) -> GateResult:
    raise _unbuilt("every-claim-has-source", "source-notes")
