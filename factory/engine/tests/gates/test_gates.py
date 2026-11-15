"""Module 8 gate acceptance: stop at the first failure, command gates by exit code, feedback fields from command output."""

import subprocess
from pathlib import Path

import pytest

from factory_engine import gates
from factory_engine.atomic import read_jsonl
from factory_engine.config import Config
from factory_engine.errors import FactoryError
from factory_engine.gates import (cmd_gate_result, known_checks, parse_junit, record_gates, run_gates,
                                  use_command_runner)
from factory_engine.checks import CHECKS, resolve
from factory_engine.state import init_run, read_run
from factory_engine.types import GateContext, GateResult, GateSpec, Request, Source

JUNIT = """<?xml version="1.0"?>
<testsuite name="api" tests="3" failures="1" errors="0">
  <testcase classname="api.test_auth" name="test_refresh_token_expired"><failure message="401 != 200"/></testcase>
  <testcase classname="api.test_auth" name="test_refresh_token_ok"/>
  <testcase classname="api.test_auth" name="test_logout"/>
</testsuite>
"""


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(cwd), *args],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def make_repo(tmp_path: Path) -> tuple[Path, str]:
    """A repo with one committed file, and the sha of that base commit."""
    repo = tmp_path / "wt"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main", str(repo))
    (repo / "services").mkdir()
    (repo / "services" / "auth.py").write_text("x = 1\n")
    (repo / "web").mkdir()
    (repo / "web" / "app.js").write_text("y = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def make_run(tmp_path: Path, worktree: Path):
    rq = Request("gh-1", Source("cli", "x", "t", "b", [], None, []), "sha", "repo", "t", "bug", None, None, [])
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    ref = init_run(tmp_path / "home", repo, "local/repo", "run-1", rq, branch="run-1", worktree=worktree,
                   kit_hash="x")
    return ref.run_dir, read_run(ref.run_dir)


def ctx_for(run, worktree: Path, *, task_base: str | None = None, artifact: Path | None = None,
            task_dir: Path | None = None, scope: list[str] | None = None, deny: list[str] | None = None) -> GateContext:
    return GateContext(run=run, stage="verify", task_id="be-tests", worktree=worktree, task_dir=task_dir,
                       artifact=artifact, task_base=task_base, scope=scope or [], deny=deny or [],
                       cfg=Config(machine={}, repo={}))


def cmd(argv: list[str]) -> GateSpec:
    return GateSpec(kind="cmd", cmd=argv, check=None, schema=None, args={})


def check(name: str) -> GateSpec:
    return GateSpec(kind="check", cmd=None, check=name, schema=None, args={})


class Stub:
    """A command runner that replays exit codes by argv and records each call."""

    def __init__(self, codes: dict[tuple[str, ...], tuple[int, str]]):
        self.codes = codes
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, ctx):
        self.calls.append(tuple(argv))
        return self.codes[tuple(argv)]


def test_gates_run_in_order_and_stop_at_the_first_failure(tmp_path):
    worktree, base = make_repo(tmp_path)
    _, run = make_run(tmp_path, worktree)
    stub = Stub({("a",): (0, ""), ("b",): (3, "b broke\n"), ("c",): (0, "")})
    with use_command_runner(stub):
        results = run_gates([cmd(["a"]), cmd(["b"]), cmd(["c"])], ctx_for(run, worktree, task_base=base))
    assert [r.passed for r in results] == [True, False]
    assert stub.calls == [("a",), ("b",)]  # c never ran


def test_a_failing_gate_returns_the_output_tail_of_the_last_200_lines(tmp_path):
    worktree, base = make_repo(tmp_path)
    _, run = make_run(tmp_path, worktree)
    output = "\n".join(f"line {i}" for i in range(1, 301)) + "\n"
    with use_command_runner(Stub({("make", "test"): (1, output)})):
        (result,) = run_gates([cmd(["make", "test"])], ctx_for(run, worktree, task_base=base))
    lines = result.output_tail.splitlines()
    assert len(lines) == 200 and lines[0] == "line 101" and lines[-1] == "line 300"


def test_a_cmd_gate_passes_on_exit_0_and_fails_on_any_other_exit(tmp_path):
    worktree, base = make_repo(tmp_path)
    _, run = make_run(tmp_path, worktree)
    for code in (1, 2, 3, 127):
        with use_command_runner(Stub({("t",): (code, "")})):
            (r,) = run_gates([cmd(["t"])], ctx_for(run, worktree, task_base=base))
        assert (r.passed, r.details["exit_code"]) == (False, code)
    with use_command_runner(Stub({("t",): (0, "")})):
        (r,) = run_gates([cmd(["t"])], ctx_for(run, worktree, task_base=base))
    assert r.passed


def test_a_missing_gate_binary_is_a_task_error_not_a_failed_gate(tmp_path):
    worktree, base = make_repo(tmp_path)
    _, run = make_run(tmp_path, worktree)

    def missing(argv, ctx):
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    with use_command_runner(missing), pytest.raises(FactoryError) as err:
        run_gates([cmd(["nope-tool"])], ctx_for(run, worktree, task_base=base))
    assert err.value.code == "gate.command_missing" and err.value.kind == "human"


def test_feedback_fields_come_from_the_command_output_and_git(tmp_path):
    worktree, base = make_repo(tmp_path)
    (worktree / "services" / "auth.py").write_text("x = 2\n")
    git(worktree, "commit", "-q", "-am", "fix attempt")
    junit = tmp_path / "be.junit.xml"
    junit.write_text(JUNIT)
    _, run = make_run(tmp_path, worktree)
    ctx = ctx_for(run, worktree, task_base=base, artifact=junit)
    result = cmd_gate_result(["make", "test-api"], 1, "FAILED test_refresh_token_expired\n", ctx)
    assert (result.passed, result.code) == (False, "gate.exit_code")
    assert result.details == {"exit_code": 1, "failed_tests": ["test_refresh_token_expired"],
                              "changed_files": ["services/auth.py"]}
    assert result.output_tail == "FAILED test_refresh_token_expired"


def test_a_passing_cmd_result_carries_no_failure_details(tmp_path):
    worktree, base = make_repo(tmp_path)
    _, run = make_run(tmp_path, worktree)
    result = cmd_gate_result(["make"], 0, "all green", ctx_for(run, worktree, task_base=base))
    assert result.passed and result.output_tail == ""


def test_parse_junit_counts_cases_and_names_only_the_failed_ones(tmp_path):
    path = tmp_path / "r.xml"
    path.write_text(JUNIT)
    report = parse_junit([path, tmp_path / "missing.xml"])
    assert report.total == 3
    assert report.failed == ["test_refresh_token_expired"]


def test_parse_junit_ignores_a_file_that_is_not_xml(tmp_path):
    path = tmp_path / "bad.xml"
    path.write_text("<testsuite><testcase")
    assert parse_junit([path]).total == 0


def test_a_schema_gate_reads_the_artifact_against_its_schema(tmp_path):
    worktree, base = make_repo(tmp_path)
    _, run = make_run(tmp_path, worktree)
    good = tmp_path / "fb.json"
    good.write_text('{"schema_version": 1, "from_stage": "a", "to_stage": "b", "loop": 1, "max": 2, "gate": "g",'
                    ' "exit_code": 1, "failed_tests": [], "output_tail": "", "changed_files": [], "at": "t"}')
    schema = GateSpec(kind="schema", cmd=None, check=None, schema="feedback", args={})
    assert run_gates([schema], ctx_for(run, worktree, artifact=good))[0].passed
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    (fail,) = run_gates([schema], ctx_for(run, worktree, artifact=bad))
    assert (fail.passed, fail.code) == (False, "gate.schema")
    (none,) = run_gates([schema], ctx_for(run, worktree, artifact=None))
    assert (none.passed, none.code) == (False, "gate.no_artifact")


def test_the_scope_diff_check_is_resolved_by_name_and_fails_outside_scope(tmp_path):
    worktree, base = make_repo(tmp_path)
    (worktree / "web" / "app.js").write_text("y = 2\n")
    git(worktree, "commit", "-q", "-am", "touched the web folder")
    _, run = make_run(tmp_path, worktree)
    ctx = ctx_for(run, worktree, task_base=base, scope=["services/**"])
    (result,) = run_gates([check("scope-diff")], ctx)
    assert (result.passed, result.code) == (False, "gate.scope_violation")
    assert result.details["files"] == ["web/app.js"]


def test_record_gates_logs_the_outcome_but_not_the_output(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    secret_output = "token=sk-live-123 leaked"
    results = [GateResult(passed=True, gate="cmd: [a]", code="ok", output_tail="", details={"exit_code": 0}),
               GateResult(passed=False, gate="cmd: [b]", code="gate.exit_code", output_tail=secret_output,
                          details={"exit_code": 3})]
    record_gates(run_dir, results)
    events = read_jsonl(run_dir / "events.jsonl")
    assert [(e["type"], e["data"]["gate"]) for e in events] == [("gate_passed", "cmd: [a]"), ("gate_failed", "cmd: [b]")]
    assert events[1]["data"]["exit_code"] == 3
    assert secret_output not in (run_dir / "events.jsonl").read_text()


def test_known_checks_lists_every_registered_name_without_importing_their_modules():
    assert known_checks() == set(CHECKS) == {
        "scope-diff", "helpers-ledger", "type-resolved", "decision-approved", "packet-hash-matches",
        "no-blocking-findings", "evidence-cites-code", "every-claim-has-source", "lint-clean",
        "build-matches-stack",
    }


def test_a_check_whose_module_is_not_built_fails_fast_when_it_runs(tmp_path, monkeypatch):
    from factory_engine import checks

    monkeypatch.setitem(checks.CHECKS, "helpers-ledger", "not_a_module_yet:check_helpers_ledger")
    worktree, base = make_repo(tmp_path)
    _, run = make_run(tmp_path, worktree)
    with pytest.raises(FactoryError) as err:
        run_gates([check("helpers-ledger")], ctx_for(run, worktree, task_base=base))
    assert err.value.code == "config.invalid" and err.value.kind == "fail_fast"


def test_an_unknown_check_name_is_refused(tmp_path):
    with pytest.raises(FactoryError, match="no check named"):
        resolve("made-up-check")


def test_the_source_check_refuses_to_pass_because_the_spec_does_not_say_how_a_claim_is_checked(tmp_path):
    worktree, base = make_repo(tmp_path)
    _, run = make_run(tmp_path, worktree)
    with pytest.raises(FactoryError) as err:
        run_gates([check("every-claim-has-source")], ctx_for(run, worktree, task_base=base))
    assert err.value.code == "config.invalid"


def test_a_review_check_with_no_artifact_fails_the_gate_and_never_passes(tmp_path):
    worktree, base = make_repo(tmp_path)
    _, run = make_run(tmp_path, worktree)
    for name in ("no-blocking-findings", "evidence-cites-code"):
        (r,) = run_gates([check(name)], ctx_for(run, worktree, task_base=base))
        assert (r.passed, r.code) == (False, "gate.no_artifact"), name


def test_gate_commands_are_argument_lists(tmp_path):
    worktree, base = make_repo(tmp_path)
    _, run = make_run(tmp_path, worktree)
    with pytest.raises(FactoryError, match="non-empty command list"):
        run_gates([GateSpec(kind="cmd", cmd=[], check=None, schema=None, args={})], ctx_for(run, worktree))


# --- Report schemas (accepted by the owner, wave 3 D1): the gates that read them, and bug-fix at run time ----------

def _stage_ctx(tmp_path, worktree, artifact_name, doc, *, stage="review"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    run_dir, run = make_run(tmp_path, worktree)
    task_dir = run_dir / "tasks" / "t1"
    task_dir.mkdir(parents=True)
    artifact = task_dir / artifact_name
    artifact.write_text(doc if isinstance(doc, str) else __import__("json").dumps(doc))
    return ctx_for(run, worktree, artifact=artifact, task_dir=task_dir)


def test_a_schema_gate_for_each_draft_schema_passes_a_good_artifact_and_fails_a_bad_one(tmp_path):
    worktree, _ = make_repo(tmp_path)
    good = {"stage-report": {"schema_version": 1, "stage": "fix", "summary": "done"},
            "test-report": {"schema_version": 1, "total": 3, "failed": []},
            "source-notes": {"schema_version": 1, "sources": [{"address": "u", "says": "s", "trust": "high"}]},
            "review-findings": {"schema_version": 1, "findings": []}}
    for name, doc in good.items():
        ctx = _stage_ctx(tmp_path / name, worktree, "a.json", doc)
        (r,) = run_gates([GateSpec(kind="schema", cmd=None, check=None, schema=name, args={})], ctx)
        assert r.passed, (name, r.output_tail)
        ctx = _stage_ctx(tmp_path / (name + "-bad"), worktree, "a.json", {"not": "it"})
        (r,) = run_gates([GateSpec(kind="schema", cmd=None, check=None, schema=name, args={})], ctx)
        assert (r.passed, r.code) == (False, "gate.schema"), name


def test_no_blocking_findings_fails_on_medium_or_high_and_passes_on_low(tmp_path):
    worktree, _ = make_repo(tmp_path)
    f = lambda sev: {"file": "services/auth.py", "line": 1, "severity": sev, "rule": "r"}
    for sev, passes in (("low", True), ("medium", False), ("high", False)):
        ctx = _stage_ctx(tmp_path / sev, worktree, "standards.json", {"schema_version": 1, "findings": [f(sev)]})
        r = resolve("no-blocking-findings")(check("no-blocking-findings"), ctx)
        assert r.passed is passes, sev
        if not passes:
            assert r.code == "gate.blocking_findings" and "services/auth.py:1" in r.output_tail


def test_evidence_cites_code_needs_claims_that_point_at_real_lines(tmp_path):
    worktree, _ = make_repo(tmp_path)                                  # services/auth.py has one line
    report = lambda *claims: {"schema_version": 1, "stage": "root-cause", "summary": "s",
                              "claims": [{"claim": "c", "file": f, "line": n} for f, n in claims]}
    cases = [([("services/auth.py", 1)], True), ([], False), ([("services/auth.py", 9)], False),
             ([("services/missing.py", 1)], False), ([("../outside.py", 1)], False)]
    for i, (claims, passes) in enumerate(cases):
        ctx = _stage_ctx(tmp_path / str(i), worktree, "cause.json", report(*claims))
        r = resolve("evidence-cites-code")(check("evidence-cites-code"), ctx)
        assert r.passed is passes, claims


def test_write_test_report_turns_junit_into_the_artifact_the_test_report_schema_accepts(tmp_path):
    from factory_engine.gates import write_test_report
    junit = tmp_path / "be.junit.xml"
    junit.write_text(JUNIT)
    out = write_test_report([junit], tmp_path / "test-report.json")
    doc = __import__("json").loads(out.read_text())
    assert doc == {"schema_version": 1, "total": 3, "failed": ["test_refresh_token_expired"]}
    from factory_engine.validate import validate
    validate(doc, "test-report")


def test_bug_fix_no_longer_fails_with_config_invalid_at_its_schema_and_check_gates(tmp_path):
    """Before the drafts, bug-fix's {schema: stage-report} and {schema: test-report} gates and its two checks raised
    config.invalid at run time. Now each gate evaluates the artifact it is given."""
    from factory_engine.workflow import load_workflow
    worktree, _ = make_repo(tmp_path)
    wf = load_workflow(tmp_path, Config(machine={}, repo={}), "bug-fix")
    report = {"schema_version": 1, "stage": "root-cause", "summary": "s",
              "claims": [{"claim": "c", "file": "services/auth.py", "line": 1}]}
    ctx = _stage_ctx(tmp_path / "rc", worktree, "cause.json", report, stage="root-cause")
    root_cause = next(s for s in wf.stages if s.id == "root-cause")
    results = run_gates(root_cause.gate, ctx)
    assert [r.passed for r in results] == [True, True] and not any(r.code == "config.invalid" for r in results)
    verify = next(s for s in wf.stages if s.id == "verify")
    test_gate = next(g for g in verify.gate if g.kind == "schema")
    ctx = _stage_ctx(tmp_path / "v", worktree, "test-report.json", {"schema_version": 1, "total": 1, "failed": []})
    assert run_gates([test_gate], ctx)[0].passed
