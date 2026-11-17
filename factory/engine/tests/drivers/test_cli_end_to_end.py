"""End to end through the CLI only: a seeded repo, `add`, then `run`, to a finished `chore` run.

The worker and the pull request service are the fakes, injected through the CLI's factories. Nothing calls the
engine's Python API. The run's state is read from its folder, which is what the CLI writes.

The second test runs the shipped bug-fix workflow the same way (decision M2). The seeded repo has no repro script, no
Makefile and no `web/` folder, so the `cmd` gates are stubbed through `gates.use_command_runner`. The `cmd` tasks are not
stubbed that way: they go to the worker, so the scripted worker writes their reports. The run stops at `propose`, a
`factory decide` answers it, and a second `factory run` finishes it.
"""

import json
from pathlib import Path

import pytest

from engine_fixtures import TRIAGE_JSON, chore_script  # noqa: E402

from cli_fixtures import KIT, seed_repo
from factory_engine import cli, decisions, gates, skills, state
from factory_engine.adapters.worker.base import Capabilities
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
from factory_engine.fake_prs import FakePullRequests


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FACTORY_WORKTREE_ROOT", str(tmp_path / "wt"))
    skills.use_kit(KIT)
    yield seed_repo(tmp_path)
    skills.use_kit(Path(skills.__file__).resolve().parents[2])


def _cli(argv: list[str], capsys, **factories) -> tuple[int, dict]:
    code = cli.main(argv, **factories)
    out = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(out[-1])


def test_a_chore_run_reaches_done_through_the_cli_alone(seeded, capsys, monkeypatch, tmp_path):
    spawned: list[str] = []
    monkeypatch.setattr(cli.api, "spawn_engine", lambda repo, run_id: spawned.append(run_id) or None)
    prs = FakePullRequests()

    code, added = _cli(["add", "Bump the lint config", "--type", "chore", "--repo", str(seeded), "--json", "--no-run"],
                       capsys)
    assert code == 0 and added["ok"] is True
    run_id = added["data"]["run_id"]

    run_dir = state.find_run(state.factory_home(), run_id).run_dir
    script, writes = chore_script(run_dir)
    worker = FakeWorkerAdapter(script, writes=writes)

    code, driven = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys,
                        worker_factory=lambda cfg: {"claude": worker},
                        tracker_factory=lambda repo, cfg: _tracker(),
                        prs_factory=lambda repo, cfg: prs)
    assert code == 0, driven
    assert driven["data"]["runs"] == {run_id: "done"}
    assert state.read_run(run_dir).status == "done"
    assert spawned == []  # `add --no-run` and `run` start no detached engine


BUG_FIX_TASKS = ["repro", "cause", "plan", "backend", "frontend", "be-tests", "fe-tests", "e2e", "standards", "spec"]
BUG_FIX_OUT = {"repro": "repro.json", "cause": "cause.json", "plan": "plan.json", "backend": "backend.json",
               "frontend": "frontend.json", "be-tests": "be.junit.xml", "fe-tests": "fe.junit.xml",
               "e2e": "e2e.junit.xml", "standards": "standards.json", "spec": "spec.json"}


def _stage_report(stage: str) -> str:
    claim = {"claim": "x is set here", "file": "services/api.py", "line": 1}
    return json.dumps({"schema_version": 1, "stage": stage, "summary": f"{stage} done", "claims": [claim]})


_TEST_REPORT = json.dumps({"schema_version": 1, "total": 3, "failed": []})
_REVIEW_FINDINGS = json.dumps({"schema_version": 1, "findings": [
    {"file": "services/api.py", "line": 1, "severity": "low", "rule": "naming", "message": "a nit"}]})


def bug_fix_script(run_dir: Path) -> tuple[dict, dict]:
    """Triage and the ten bug-fix tasks, each with a valid artifact. `chore_script` is the model; its `rules` entry
    is reused with a triage answer that picks bug-fix."""
    script, writes = chore_script(run_dir)
    script = {"rules": script["rules"]}
    triage = {**json.loads(TRIAGE_JSON), "type": "bug", "workflow": "bug-fix"}
    writes = {"rules": {"triage.json": json.dumps(triage)}}
    for task in BUG_FIX_TASKS:
        out = BUG_FIX_OUT[task]
        script[task] = [ok(run_dir / "tasks" / task / "work" / out)]
        if task in ("be-tests", "fe-tests", "e2e"):
            writes[task] = {out: _TEST_REPORT}
        elif task in ("standards", "spec"):
            writes[task] = {out: _REVIEW_FINDINGS}
        else:
            writes[task] = {out: _stage_report(task)}
    return script, writes


def test_a_bug_fix_run_stops_at_propose_is_answered_by_decide_and_reaches_done(seeded, capsys, monkeypatch):
    spawned: list[str] = []
    monkeypatch.setattr(cli.api, "spawn_engine", lambda repo, run_id: spawned.append(run_id) or None)
    prs = FakePullRequests()
    gate_commands: list[list[str]] = []

    def stub_runner(argv, ctx):
        gate_commands.append(list(argv))
        return 0, ""

    code, added = _cli(["add", "Fix the off-by-one in the report", "--type", "bug", "--repo", str(seeded), "--json",
                        "--no-run"], capsys)
    assert code == 0 and added["ok"] is True
    run_id = added["data"]["run_id"]
    run_dir = state.find_run(state.factory_home(), run_id).run_dir
    script, writes = bug_fix_script(run_dir)
    # Claude reports native subagents, so `backend` stays one task. The fake defaults to "none" and would split it.
    worker = FakeWorkerAdapter(script, writes=writes, capabilities=Capabilities(subagents="native", usage=True))
    factories = dict(worker_factory=lambda cfg: {"claude": worker}, tracker_factory=lambda repo, cfg: _tracker(),
                     prs_factory=lambda repo, cfg: prs)

    with gates.use_command_runner(stub_runner):
        code, parked = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **factories)
        assert code == 3, parked  # the engine exits 3 when a run waits on a person
        assert parked["data"]["runs"] == {run_id: "awaiting_approval"}
        assert state.read_run(run_dir).stage == "propose"
        assert {c.task_id for c in worker.started} == {"rules", "repro", "cause", "plan"}  # nothing past the stop ran

        packet = decisions.read_decision(run_dir, "propose", 1)["packet"]
        code, decided = _cli(["decide", run_id, "--repo", str(seeded), "--json", "--packet", packet["sha"],
                              "D1=approve"], capsys)
        assert code == 0 and decided["data"]["status"] == "approved", decided
        assert state.read_run(run_dir).status == "awaiting_approval"  # the answer starts an engine; it does not run one

        code, driven = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **factories)

    assert code == 0, driven
    assert driven["data"]["runs"] == {run_id: "done"}
    assert state.read_run(run_dir).status == "done"
    assert sorted(c.task_id for c in worker.started) == sorted(["rules", *BUG_FIX_TASKS])
    assert ["scripts/repro-fails.sh"] in gate_commands and ["make", "build"] in gate_commands
    assert ["scripts/repro-now-passes.sh"] in gate_commands
    assert spawned == [run_id]  # only `decide` started an engine, and the test ran it by hand instead
    assert prs.calls == ["create"]


def _tracker():
    from factory_engine.adapters.tracker.fake import FakeTracker
    return FakeTracker()
