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

# (argv, ctx) -> (exit code, combined output). Module 9's CommandAdapter replaces the default when it is built.
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


def _default_runner(cmd: list[str], ctx: GateContext) -> tuple[int, str]:
    raise FactoryError("config.invalid", "a cmd gate needs module 9's CommandAdapter, which is not built",
                       hint="build module 9 before a workflow with a cmd gate runs")


_runner: CommandRunner = _default_runner


@contextmanager
def use_command_runner(runner: CommandRunner) -> Iterator[None]:
    """Run cmd gates through `runner` inside the block. Module 9 wires CommandAdapter here; tests pass a stub."""
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


def cmd_gate_result(cmd: list[str], exit_code: int, output: str, ctx: GateContext) -> GateResult:
    """The result of a command that ran, from its exit code and output (module 8, class table).

    Used for a cmd gate and for a failed cmd task: the spec treats a non-zero exit from a command task as a gate
    failure, so 6B passes its command's result here and gets the same rework feedback. Zero passes. Any other exit
    fails with the output tail, the failing test names from the task's JUnit report (ctx.artifact), and the files
    git reports as changed."""
    name = "cmd: [" + ", ".join(cmd) + "]"
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
    name = f"schema: {spec.schema}"
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


# These checks read an artifact whose shape the spec has not defined. Each fails fast until that shape exists,
# so a gate never passes an artifact it cannot read.

def _unbuilt(check: str, schema: str) -> FactoryError:
    return FactoryError("config.invalid", f"check {check!r} reads {schema}, which has no fields in the spec yet",
                        hint=f"define {schema} in the module that produces it before a gate uses {check}")


def check_findings(spec: GateSpec, ctx: GateContext) -> GateResult:
    raise _unbuilt("no-blocking-findings", "review-findings")


def check_evidence(spec: GateSpec, ctx: GateContext) -> GateResult:
    raise _unbuilt("evidence-cites-code", "stage-report")


def check_sources(spec: GateSpec, ctx: GateContext) -> GateResult:
    raise _unbuilt("every-claim-has-source", "source-notes")
