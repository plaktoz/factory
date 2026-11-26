"""End to end through the CLI only: a seeded repo, `add`, then `run`, to a finished `chore` run.

The worker, the command adapter and the pull request service are fakes, injected through the CLI's factories. Nothing
calls the engine's Python API. The run's state is read from its folder, which is what the CLI writes.

The second test runs the shipped bug-fix workflow the same way (decision M2). The seeded repo has no repro script, no
Makefile and no `web/` folder, so the `cmd` gates are stubbed through `gates.use_command_runner`. The `cmd` tasks are not
stubbed that way: they go to the command fake, which writes their reports. The run stops at `propose`, a
`factory decide` answers it, and a second `factory run` finishes it.
"""

import json
import subprocess
from pathlib import Path

import pytest

from engine_fixtures import TRIAGE_JSON, chore_script  # noqa: E402

from cli_fixtures import KIT, seed_repo
from factory_engine import cli, decisions, gates, skills, state
from factory_engine.adapters.worker.base import Capabilities
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
from factory_engine.fake_prs import FakePullRequests
from factory_engine.gh import GitHubTracker


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
    worker, command = _split_worker_and_command(script, writes)

    factories = dict(worker_factory=lambda cfg: {"claude": worker}, command_factory=lambda cfg: command,
                     tracker_factory=lambda repo, cfg: _tracker(), prs_factory=lambda repo, cfg: prs)
    code, driven = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **factories)
    assert code == 3, driven
    assert driven["data"]["runs"] == {run_id: "awaiting_approval"}
    prs.human_merge(state.read_run(run_dir).pr)
    code, driven = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **factories)
    assert code == 0, driven
    assert driven["data"]["runs"] == {run_id: "done"}
    assert state.read_run(run_dir).status == "done"
    assert spawned == []  # `add --no-run` and `run` start no detached engine
    assert {c.task_id for c in command.started} == {"rules", "check"}  # the cmd tasks, not the skill tasks
    assert {c.task_id for c in worker.started} == {"change"}


BUG_FIX_TASKS = ["repro", "cause", "plan", "backend", "frontend", "be-tests", "fe-tests", "e2e", "standards", "spec"]
BUG_FIX_OUT = {"repro": "repro.json", "cause": "cause.json", "plan": "plan.json", "backend": "backend.json",
               "frontend": "frontend.json", "be-tests": "be.junit.xml", "fe-tests": "fe.junit.xml",
               "e2e": "e2e.junit.xml", "standards": "standards.json", "spec": "spec.json"}


def _stage_report(stage: str) -> str:
    claim = {"claim": "x is set here", "file": "services/api.py", "line": 1}
    return json.dumps({"schema_version": 1, "stage": stage, "summary": f"{stage} done", "claims": [claim]})


# A JUnit file, as a test runner writes it: the engine counts the <testcase> elements, so the verify gate sees 3 tests.
_JUNIT_THREE_PASS = ('<testsuite name="s" tests="3" failures="0">'
                     '<testcase name="a"/><testcase name="b"/><testcase name="c"/></testsuite>')
_REVIEW_FINDINGS = json.dumps({"schema_version": 1, "findings": [
    {"file": "services/api.py", "line": 1, "severity": "low", "rule": "naming", "message": "a nit"}]})


REWORKED = {"backend", "frontend", "be-tests", "fe-tests", "e2e"}  # the tasks of `fix` and `verify`: they run again on a rework


def bug_fix_script(run_dir: Path, *, verify_failures: int = 0) -> tuple[dict, dict]:
    """Triage and the ten bug-fix tasks, each with a valid artifact. `chore_script` is the model; its `rules` entry
    is reused with a triage answer that picks bug-fix. Each failure of verify sends the run back to `fix`, so the tasks
    of `fix` and `verify` get one more scripted attempt for each."""
    script, writes = chore_script(run_dir)
    script = {"rules": script["rules"]}
    triage = {**json.loads(TRIAGE_JSON), "type": "bug", "workflow": "bug-fix"}
    writes = {"rules": {"triage.json": json.dumps(triage)}}
    for task in BUG_FIX_TASKS:
        out = BUG_FIX_OUT[task]
        script[task] = [ok(run_dir / "tasks" / task / "work" / out)] * (1 + (verify_failures if task in REWORKED else 0))
        if task in ("be-tests", "fe-tests", "e2e"):
            writes[task] = {out: _JUNIT_THREE_PASS}
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
    worker, command = _split_worker_and_command(script, writes, native=True)
    factories = dict(worker_factory=lambda cfg: {"claude": worker}, command_factory=lambda cfg: command,
                     tracker_factory=lambda repo, cfg: _tracker(), prs_factory=lambda repo, cfg: prs)

    with gates.use_command_runner(stub_runner):
        code, parked = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **factories)
        assert code == 3, parked  # the engine exits 3 when a run waits on a person
        assert parked["data"]["runs"] == {run_id: "awaiting_approval"}
        assert state.read_run(run_dir).stage == "propose"
        assert {c.task_id for c in worker.started} == {"repro", "cause", "plan"}  # nothing past the stop ran
        assert {c.task_id for c in command.started} == {"rules"}

        packet = decisions.read_decision(run_dir, "propose", 1)["packet"]
        code, decided = _cli(["decide", run_id, "--repo", str(seeded), "--json", "--packet", packet["sha"],
                              "D1=approve"], capsys)
        assert code == 0 and decided["data"]["status"] == "approved", decided
        assert state.read_run(run_dir).status == "awaiting_approval"  # the answer starts an engine; it does not run one

        code, driven = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **factories)

    assert code == 3, driven
    assert driven["data"]["runs"] == {run_id: "awaiting_approval"}
    prs.human_merge(state.read_run(run_dir).pr)
    with gates.use_command_runner(stub_runner):
        code, driven = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **factories)
    assert code == 0, driven
    assert driven["data"]["runs"] == {run_id: "done"}
    assert state.read_run(run_dir).status == "done"
    skill_tasks = [t for t in BUG_FIX_TASKS if t not in CMD_TASKS]
    assert sorted(c.task_id for c in worker.started) == sorted(skill_tasks)
    assert sorted(c.task_id for c in command.started) == sorted(["rules", *CMD_TASKS & set(BUG_FIX_TASKS)])
    assert ["scripts/repro-fails.sh"] in gate_commands and ["make", "build"] in gate_commands
    assert ["scripts/repro-now-passes.sh"] in gate_commands
    assert spawned == [run_id]  # only `decide` started an engine, and the test ran it by hand instead
    # Opening asks the request's author to review (owner decision D1). Then one read at the merge review, and no merge
    # until the test makes one on the fake. The green check is not reached here: the fake's CI stays pending.
    assert prs.calls == ["create", "request_reviewers", "state"]


CMD_TASKS = {"rules", "check", "be-tests", "fe-tests", "e2e"}  # the cmd tasks of the shipped workflows


def test_a_bug_fix_run_with_one_rework_from_verify_ends_done_and_cleaned_up_after_the_human_merge(seeded, capsys,
                                                                                                 monkeypatch):
    """Section 20, first integration test: issue, run, triage, approval through `factory decide`, one rework from
    verify, PR, human merge, cleanup. The gate `repro-now-passes.sh` fails the first time verify runs and passes the
    second, so verify routes back to `fix` once (`on_fail: {goto: fix}`). After the merge the run is `done`, its run
    worktree is gone from disk and `run_done` is in the events."""
    monkeypatch.setattr(cli.api, "spawn_engine", lambda repo, run_id: None)
    prs = FakePullRequests()
    repro_now_passes: list[int] = []

    def stub_runner(argv, ctx):
        if argv == ["scripts/repro-now-passes.sh"]:
            repro_now_passes.append(1)
            return (1, "the repro still fails") if len(repro_now_passes) == 1 else (0, "")
        return 0, ""

    code, added = _cli(["add", "Fix the off-by-one in the report", "--type", "bug", "--repo", str(seeded), "--json",
                        "--no-run"], capsys)
    assert code == 0 and added["ok"] is True
    run_id = added["data"]["run_id"]
    run_dir = state.find_run(state.factory_home(), run_id).run_dir
    script, writes = bug_fix_script(run_dir, verify_failures=1)
    worker, command = _split_worker_and_command(script, writes, native=True)
    factories = dict(worker_factory=lambda cfg: {"claude": worker}, command_factory=lambda cfg: command,
                     tracker_factory=lambda repo, cfg: _tracker(), prs_factory=lambda repo, cfg: prs)

    with gates.use_command_runner(stub_runner):
        code, parked = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **factories)
        assert code == 3 and state.read_run(run_dir).stage == "propose", parked
        packet = decisions.read_decision(run_dir, "propose", 1)["packet"]
        code, decided = _cli(["decide", run_id, "--repo", str(seeded), "--json", "--packet", packet["sha"],
                              "D1=approve"], capsys)
        assert code == 0 and decided["data"]["status"] == "approved", decided
        code, driven = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **factories)
    assert code == 3 and driven["data"]["runs"] == {run_id: "awaiting_approval"}, driven

    run = state.read_run(run_dir)
    assert run.loops == {"verify->fix": 1}  # one rework, from verify back to fix
    events = [e.type for e in state.read_events(run_dir)]
    assert events.count("gate_failed") == 1 and repro_now_passes  # the verify gate failed once, then passed
    assert events.count("routed_back") == 1
    assert sorted(c.task_id for c in worker.started if c.task_id in ("backend", "frontend")) == [
        "backend", "backend", "frontend", "frontend"]  # `fix` ran twice
    assert [c.task_id for c in command.started].count("be-tests") == 2  # and so did `verify`
    assert run.pr is not None and prs.prs[run.pr.number].state == "open"
    worktree = run.worktree
    assert worktree.exists()  # the run keeps its worktree until the merge

    prs.human_merge(run.pr)
    with gates.use_command_runner(stub_runner):
        code, driven = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **factories)
    assert code == 0 and driven["data"]["runs"] == {run_id: "done"}, driven
    assert state.read_run(run_dir).status == "done"
    assert not worktree.exists()  # cleanup: the run worktree is gone from disk
    events = [e.type for e in state.read_events(run_dir)]
    assert events.count("merged") == 1 and events.count("run_done") == 1


def _split_worker_and_command(script, writes, *, native: bool = False):
    """The cmd tasks go to a command fake and the skill tasks to the worker fake, as the engine routes them (item 12).
    Claude reports native subagents, so `backend` stays one task. The fake defaults to "none" and would split it."""
    cap = Capabilities(subagents="native", usage=True) if native else None
    worker_script = {t: r for t, r in script.items() if t not in CMD_TASKS}
    command_script = {t: r for t, r in script.items() if t in CMD_TASKS}
    worker = FakeWorkerAdapter(worker_script, writes={t: w for t, w in writes.items() if t not in CMD_TASKS},
                               capabilities=cap)
    command = FakeWorkerAdapter(command_script, writes={t: w for t, w in writes.items() if t in CMD_TASKS},
                                capabilities=Capabilities(subagents="none", usage=False))
    return worker, command


def _tracker():
    from factory_engine.adapters.tracker.fake import FakeTracker
    return FakeTracker()


class RecordedGh:
    """A `gh` runner that replays what GitHub answers: one open `factory` issue, and it records every call. The label
    and comment calls (`issue edit`, `issue comment`) are the factory telling the issue where its run stands."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.issues = json.dumps([{
            "number": 7, "title": "Fix the off-by-one in the report", "body": "The totals miss the last row.",
            "labels": [{"name": "factory"}, {"name": "bug"}], "author": {"login": "plaktoz"},
            "updatedAt": "2026-11-26T00:00:00Z"}])

    def __call__(self, args):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, self.issues if args[:2] == ["issue", "list"] else "", "")

    def labels_added(self) -> list[str]:
        return [a[a.index("--add-label") + 1] for a in self.calls if a[:2] == ["issue", "edit"]]


def test_a_bug_fix_run_that_starts_as_a_github_issue_is_synced_run_decided_merged_and_cleaned_up(seeded, capsys,
                                                                                                monkeypatch):
    """Section 20, first integration test, with its first word: the request is an issue. `factory sync` reads it
    through `GitHubTracker` (a recorded `gh`), the run is the same bug-fix chain as above, and the issue is told each
    state on the way (`factory:queued`, then `factory:needs-human` at the stop and the merge review, then
    `factory:done`). Nothing calls the engine's Python API."""
    monkeypatch.setattr(cli.api, "spawn_engine", lambda repo, run_id: None)
    gh = RecordedGh()
    tracker = GitHubTracker("plaktoz/report", gh)
    monkeypatch.setattr(cli.api, "default_tracker", lambda repo, cfg: tracker)
    prs = FakePullRequests()
    repro_now_passes: list[int] = []

    def stub_runner(argv, ctx):
        if argv == ["scripts/repro-now-passes.sh"]:
            repro_now_passes.append(1)
            return (1, "the repro still fails") if len(repro_now_passes) == 1 else (0, "")
        return 0, ""

    code, synced = _cli(["sync", "--repo", str(seeded), "--json"], capsys)
    assert code == 0 and len(synced["data"]["created"]) == 1, synced  # the issue became exactly one run
    run_id = synced["data"]["created"][0]
    run_dir = state.find_run(state.factory_home(), run_id).run_dir
    assert state.read_run(run_dir).request.source.ref == "plaktoz/report#7"  # the run's source is the issue

    script, writes = bug_fix_script(run_dir, verify_failures=1)
    worker, command = _split_worker_and_command(script, writes, native=True)
    factories = dict(worker_factory=lambda cfg: {"claude": worker}, command_factory=lambda cfg: command,
                     tracker_factory=lambda repo, cfg: tracker, prs_factory=lambda repo, cfg: prs)

    with gates.use_command_runner(stub_runner):
        code, parked = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **factories)
        assert code == 3 and state.read_run(run_dir).stage == "propose", parked
        packet = decisions.read_decision(run_dir, "propose", 1)["packet"]
        code, decided = _cli(["decide", run_id, "--repo", str(seeded), "--json", "--packet", packet["sha"],
                              "D1=approve"], capsys)
        assert code == 0 and decided["data"]["status"] == "approved", decided
        code, driven = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **factories)
    assert code == 3 and driven["data"]["runs"] == {run_id: "awaiting_approval"}, driven
    assert state.read_run(run_dir).loops == {"verify->fix": 1}  # one rework, from verify back to fix
    run = state.read_run(run_dir)
    worktree = run.worktree

    prs.human_merge(run.pr)
    with gates.use_command_runner(stub_runner):
        code, driven = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **factories)
    assert code == 0 and driven["data"]["runs"] == {run_id: "done"}, driven
    assert not worktree.exists()  # cleanup: the run worktree is gone from disk
    events = [e.type for e in state.read_events(run_dir)]
    assert events.count("merged") == 1 and events.count("run_done") == 1
    labels = gh.labels_added()
    assert labels[-1] == "factory:done", labels  # the issue ends told the run is done
    assert "factory:needs-human" in labels, labels  # and was told it waited on a person
