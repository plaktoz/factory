"""Item 12, gap 3: the engine writes test-report.json from the verify stage's JUnit files, and the verify gate reads
that report (module 5, report schemas: the engine writes test-report from the verify tasks' JUnit files)."""

from factory_engine import gates
from factory_engine.gates import write_test_report

JUNIT_TWO_PASS = '<testsuite><testcase name="a"/><testcase name="b"/></testsuite>'
JUNIT_ONE_FAIL = '<testsuite><testcase name="a"><failure/></testcase></testsuite>'


def test_the_report_counts_every_junit_file_of_the_stage(tmp_path):
    be = tmp_path / "be.junit.xml"
    fe = tmp_path / "fe.junit.xml"
    be.write_text(JUNIT_TWO_PASS)
    fe.write_text(JUNIT_ONE_FAIL)
    doc = write_test_report([be, fe], tmp_path / "test-report.json")
    import json
    body = json.loads(doc.read_text())
    assert body == {"schema_version": 1, "total": 3, "failed": ["a"]}


def test_a_missing_junit_file_contributes_no_cases(tmp_path):
    import json
    out = write_test_report([tmp_path / "absent.junit.xml"], tmp_path / "test-report.json")
    assert json.loads(out.read_text())["total"] == 0


def test_test_report_schema_gate_reads_the_written_report(tmp_path):
    from factory_engine.types import GateContext, GateSpec
    from factory_engine.config import Config
    report = tmp_path / "test-report.json"
    write_test_report([], report)
    spec = GateSpec(kind="schema", cmd=None, check=None, schema="test-report", args={})
    ctx = GateContext(run=None, stage="verify", task_id=None, worktree=tmp_path, task_dir=None, artifact=report,
                      task_base=None, scope=[], deny=[], cfg=Config(machine={}, repo={}))
    result = gates._schema_gate(spec, ctx)
    assert result.passed and result.code == "ok"

