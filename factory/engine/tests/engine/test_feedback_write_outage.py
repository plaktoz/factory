"""Module 8, "Errors": a feedback write that fails partway is an infrastructure error. A disk error after the first task
folder leaves the run `retrying` with the operation named, and no route is saved (no goto, no loop count). The next
pass repeats the write, and the writer skips the task folder that already holds the record, so each task folder ends
with exactly one record and the stage reruns. After `infra_wait_hours` the run is blocked. A schema failure is not an
infrastructure error and still raises. Driven through the real engine loop, with a real gate command runner stub."""

import errno
import json
from pathlib import Path

import pytest

from factory_engine import rework, state
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
from factory_engine.errors import FactoryError

from engine_helpers import TRIAGE_JSON, chore_script

RUN = "bump-q1w2e"

# One stage with two task folders, whose gate sends the run back to the same stage (a loop of one edge).
WORKFLOW = """\
name: chore
type: chore
sink: pull_request
policy: {write: true, deny_paths: []}
defaults: {retries: 0, timeout_minutes: 5, checkpoint_every_minutes: 10, max_restarts: 0}
stages:
  - id: implement
    tasks:
      - {id: a, skill: implement, out: a.json}
      - {id: b, skill: implement, out: b.json}
    gate: [{cmd: [make, build]}]
    on_fail: {goto: implement, max: 3}
"""


class BuildFailsUntil:
    """The `make build` gate: fails on its first `failures` runs, then passes. It replaces only the command runner, so
    the gate result, the routing and the feedback writer are the engine's own."""

    def __init__(self, failures: int):
        self.failures, self.calls = failures, 0

    def __call__(self, argv, ctx):
        self.calls += 1
        return (1, "build broke") if self.calls <= self.failures else (0, "")


class FullDisk:
    """Stands in for the feedback writer. While `full` is set, a record for task `task` fails with ENOSPC, as a disk
    that fills after the first task folder would. Other writes go through to the real writer."""

    def __init__(self, monkeypatch, task: str):
        self.task, self.full = task, True
        self.real = rework.write_json_atomic
        monkeypatch.setattr(rework, "write_json_atomic", self)

    def __call__(self, path, doc):
        if self.full and Path(path).parent.parent.name == self.task:
            raise OSError(errno.ENOSPC, "No space left on device")
        return self.real(path, doc)


@pytest.fixture
def outage(repo, new_run, engine, monkeypatch):
    """A run whose implement stage fails its gate, with the feedback write for task b failing until the test lets it
    through. Returns the run folder, the worker, the clock-driving engine and the disk."""
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))],
              "a": [ok(work("a", "a.json"))] * 2,
              "b": [ok(work("b", "b.json"))] * 2}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "a": {"a.json": "{}"}, "b": {"b.json": "{}"}}
    eng, worker = engine(script, writes)
    wf_dir = repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "chore.yaml").write_text(WORKFLOW)
    disk = FullDisk(monkeypatch, task="b")
    return run_dir, worker, eng, disk


def _records(run_dir: Path, task: str) -> list[str]:
    return sorted(p.name for p in (run_dir / "tasks" / task / "feedback").glob("*.json"))


def _types(run_dir: Path) -> list[str]:
    return [e.type for e in state.read_events(run_dir)]


def test_a_feedback_write_that_fails_partway_waits_as_retrying_and_the_next_pass_routes_once(outage, clock):
    run_dir, worker, eng, disk = outage
    gate = BuildFailsUntil(failures=2)  # the first pass and its retry both see a failing build, then it passes

    with _gate(gate):
        assert eng.run([RUN]).runs[RUN] == "retrying"  # the record for `a` is written, `b` fails: the run waits
        run = state.read_run(run_dir)
        assert run.status == "retrying" and run.stage == "implement"
        assert run.infra_wait is not None and run.infra_wait.last_error.startswith("feedback write: ")
        assert "No space left on device" in run.infra_wait.last_error
        assert run.loops == {}  # the route is not saved: no loop is counted yet
        assert clock.sleeps[-2:] == [5, 30]  # the write is retried with the module 8 backoff
        assert _records(run_dir, "a") == ["001-implement-to-implement.json"]
        assert _records(run_dir, "b") == []
        assert "routed_back" not in _types(run_dir) and _types(run_dir).count("infra_waiting") == 1

        disk.full = False  # the disk has room again
        assert eng.run([RUN]).runs[RUN] == "awaiting_approval"  # the next pass repeats the write, routes and reruns

    run = state.read_run(run_dir)
    assert _records(run_dir, "a") == ["001-implement-to-implement.json"]  # written once, not again
    assert _records(run_dir, "b") == ["001-implement-to-implement.json"]  # one record in each task folder
    assert run.loops == {"implement->implement": 1}  # the loop counter moved once, not once per pass
    assert _types(run_dir).count("routed_back") == 1
    assert run.infra_wait is None and _types(run_dir).count("infra_recovered") == 1
    assert [c.task_id for c in worker.started].count("a") == 2  # the stage reran: each task started a second time
    assert [c.task_id for c in worker.started].count("b") == 2


def test_a_feedback_write_outage_blocks_the_run_only_after_infra_wait_hours_and_saves_no_route(outage, clock):
    run_dir, _worker, eng, _disk = outage
    with _gate(BuildFailsUntil(failures=99)):
        assert eng.run([RUN]).runs[RUN] == "retrying"
        clock.advance(5 * 3600 + 59 * 60)  # inside the six hours: still waiting
        assert eng.run([RUN]).runs[RUN] == "retrying"
        clock.advance(120)  # past the six hours
        assert eng.run([RUN]).runs[RUN] == "blocked"
    run = state.read_run(run_dir)
    assert run.status == "blocked" and run.attention is not None and run.attention.kind == "blocked"
    assert run.stage == "implement" and run.loops == {}  # blocked where it was, with no loop counted
    blocked = [e for e in state.read_events(run_dir) if e.type == "run_blocked"]
    assert len(blocked) == 1 and "feedback write has failed for 6 hours" in blocked[0].data["reason"]


def test_a_schema_failure_in_the_feedback_record_still_raises_and_does_not_wait(outage, monkeypatch):
    run_dir, _worker, eng, disk = outage
    disk.full = False

    def refuse(obj, schema, *, file="<input>"):
        raise FactoryError("config.invalid", f"{file}: a feedback record does not match its schema")

    monkeypatch.setattr(rework, "validate", refuse)
    with _gate(BuildFailsUntil(failures=1)):
        with pytest.raises(FactoryError) as raised:
            eng.run([RUN])
    assert raised.value.code == "config.invalid"
    run = state.read_run(run_dir)
    assert run.status != "retrying" and run.infra_wait is None  # a schema failure is not an infrastructure error
    assert "routed_back" not in _types(run_dir)


def _gate(runner):
    from factory_engine import gates
    return gates.use_command_runner(runner)


# A human rework: `propose` needs an approval and its rework goes back to `root-cause`. The answer is a decision file,
# so the route survives a retry: the next pass reads the same answer and routes again.
HUMAN_WORKFLOW = """\
name: chore
type: chore
sink: pull_request
policy: {write: true, deny_paths: []}
defaults: {retries: 0, timeout_minutes: 5, checkpoint_every_minutes: 10, max_restarts: 0}
stages:
  - id: root-cause
    tasks: [{id: cause, skill: root-cause, out: cause.json}]
  - id: propose
    needs: [root-cause]
    tasks: [{id: plan, skill: propose, out: plan.json}]
    approval: human
    on_reject: {goto: root-cause}
  - id: fix
    needs: [propose]
    tasks: [{id: change, skill: implement, out: change.json}]
"""


def test_a_human_rework_whose_feedback_write_fails_keeps_its_route_and_routes_on_the_next_pass(new_run, engine, repo, monkeypatch):
    from factory_engine import decisions as D
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))],
              "cause": [ok(work("cause", "cause.json"))] * 2,
              "plan": [ok(work("plan", "plan.json"))] * 2,
              "change": [ok(work("change", "change.json"))]}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "cause": {"cause.json": "{}"},
              "plan": {"plan.json": "{}"}, "change": {"change.json": "{}"}}
    eng, _ = engine(script, writes)
    wf_dir = repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "chore.yaml").write_text(HUMAN_WORKFLOW)
    assert eng.run([RUN]).runs[RUN] == "awaiting_approval"
    visit = D.latest_visit(state.read_run(run_dir), "propose")
    doc = D.read_decision(run_dir, "propose", visit)
    D.record(run_dir, "propose", visit, packet_sha=doc["packet"]["sha"],
             choices={d["id"]: "rework" for d in doc["packet"]["decisions"]}, notes="try again", by="owner", channel="cli")

    disk = FullDisk(monkeypatch, task="cause")
    assert eng.run([RUN]).runs[RUN] == "retrying"
    run = state.read_run(run_dir)
    assert run.loops == {} and run.stage == "propose"  # nothing routed yet, so no loop is counted
    assert run.infra_wait is not None and run.infra_wait.last_error.startswith("feedback write: ")

    disk.full = False
    assert eng.run([RUN]).runs[RUN] == "awaiting_approval"  # the next pass routes from the same answer
    run = state.read_run(run_dir)
    assert run.loops == {"propose->root-cause:human": 1}
    assert _records(run_dir, "cause") == ["001-propose-to-root-cause.json"]
    assert run.infra_wait is None
    record = json.loads((run_dir / "tasks" / "cause" / "feedback" / "001-propose-to-root-cause.json").read_text())
    assert record["notes"] == "try again"


def _github_request():
    """A request from a GitHub issue, so the run opens a pull request and waits at its merge review."""
    from factory_engine.types import Request, Source
    src = Source("github", "acme/report#1", "Bump the lint config", "Bump it.", ["chore"], "alice", [])
    return Request("gh-1", src, "sha1", "repo", "Bump the lint config", "chore", "explicit", None, [])


def test_a_red_ci_feedback_write_that_fails_waits_and_the_next_pass_routes_once(new_run, engine, prs, monkeypatch):
    """Red CI at the merge review goes back through the last stage's on_fail edge. A failed feedback write waits as
    `retrying` with no route saved; the next pass reads the pull request again, still red, and routes once."""
    run_dir = new_run(request=_github_request())
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * 2,
                                  check=[ok(work("check", "check.log"))] * 2)
    eng, _ = engine(script, writes)
    eng.run([RUN])
    prs.set_ci(state.read_run(run_dir).pr, "red", "lint: FAILURE")

    disk = FullDisk(monkeypatch, task="change")
    assert eng.run([RUN]).runs[RUN] == "retrying"
    run = state.read_run(run_dir)
    assert run.loops == {} and run.infra_wait is not None and run.infra_wait.last_error.startswith("feedback write (red CI): ")
    assert "routed_back" not in _types(run_dir)

    disk.full = False
    assert eng.run([RUN]).runs[RUN] == "awaiting_approval"
    run = state.read_run(run_dir)
    assert run.loops == {"verify->implement:ci": 1}
    assert _records(run_dir, "change") == ["001-verify-to-implement.json"]
    assert _types(run_dir).count("routed_back") == 1
