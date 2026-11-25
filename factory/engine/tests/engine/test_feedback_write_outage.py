"""Module 8, "Errors": a feedback write that fails partway is an infrastructure error. A disk error after the first task
folder leaves the run `retrying` with the operation named, and the route is saved in `pending-route.json` in the run
folder, with no loop count yet. The next pass writes the saved record (the writer skips the task folder that already
holds it) and applies the saved route without running the check again, so a check that would pass now does not drop
the rework, and the loop counter moves once. After `infra_wait_hours` the run is blocked and the saved route is removed.
A schema failure is not an infrastructure error and still raises. Driven through the real engine loop, with a real gate
command runner stub."""

import errno
import json
from pathlib import Path

import pytest

from factory_engine import rework, state
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
from factory_engine.errors import FactoryError
from factory_engine.validate import validate

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
    gate = BuildFailsUntil(failures=1)  # the first pass sees a failing build; the repeat pass applies the saved route

    with _gate(gate):
        assert eng.run([RUN]).runs[RUN] == "retrying"  # the record for `a` is written, `b` fails: the run waits
        run = state.read_run(run_dir)
        assert run.status == "retrying" and run.stage == "implement"
        assert run.infra_wait is not None and run.infra_wait.last_error.startswith("feedback write: ")
        assert "No space left on device" in run.infra_wait.last_error
        assert run.loops == {}  # the route is saved, not applied: no loop is counted yet
        assert _pending(run_dir).is_file()
        assert clock.sleeps[-2:] == [5, 30]  # the write is retried with the module 8 backoff
        assert _records(run_dir, "a") == ["001-implement-to-implement.json"]
        assert _records(run_dir, "b") == []
        assert "routed_back" not in _types(run_dir) and _types(run_dir).count("infra_waiting") == 1

        disk.full = False  # the disk has room again
        assert eng.run([RUN]).runs[RUN] == "awaiting_approval"  # the next pass writes the saved record, routes and reruns

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
        assert _pending(run_dir).is_file()
        clock.advance(5 * 3600 + 59 * 60)  # inside the six hours: still waiting
        assert eng.run([RUN]).runs[RUN] == "retrying"
        clock.advance(120)  # past the six hours
        assert eng.run([RUN]).runs[RUN] == "blocked"
    run = state.read_run(run_dir)
    assert run.status == "blocked" and run.attention is not None and run.attention.kind == "blocked"
    assert run.stage == "implement" and run.loops == {}  # blocked where it was, with no loop counted
    assert not _pending(run_dir).exists()  # the block removes the saved route: a person's retry re-derives it
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
    assert not _pending(run_dir).exists()  # and no route is saved for it


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


def test_a_human_rework_wait_does_not_apply_a_route_left_by_an_earlier_gate_route(new_run, engine, repo, monkeypatch):
    """A human rework saves no route, so a pending-route.json left by an earlier gate route must not be applied to its
    feedback-write wait. The human answer is what routes the run."""
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
    # A route left in the folder by an earlier gate route (a crash after it was applied, before the file was removed).
    stale = _pending_doc(from_stage="propose", goto="root-cause", reset=["root-cause"], loop_key="propose->root-cause:gate",
                         tasks=["cause"])
    stale["feedback"] = dict(stale["feedback"], from_stage="propose", to_stage="root-cause")
    (run_dir / "pending-route.json").write_text(json.dumps(stale))

    disk = FullDisk(monkeypatch, task="cause")
    assert eng.run([RUN]).runs[RUN] == "retrying"
    disk.full = False
    assert eng.run([RUN]).runs[RUN] == "awaiting_approval"
    run = state.read_run(run_dir)
    assert run.loops == {"propose->root-cause:human": 1}  # the human route, not the stale gate route
    assert not (run_dir / "pending-route.json").exists()


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
    assert not _pending(run_dir).exists()  # a human rework saves no route: its answer is in the decision file

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


def test_a_red_ci_rework_whose_write_fails_is_still_routed_when_the_pull_request_reads_green(new_run, engine, prs, monkeypatch):
    """The dropped case for red CI: the pull request is read red, the record cannot be written, and the next pass reads
    the pull request green. The saved route is applied from the first read, so the rework is not dropped."""
    run_dir = new_run(request=_github_request())
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * 2,
                                  check=[ok(work("check", "check.log"))] * 2)
    eng, worker = engine(script, writes)
    eng.run([RUN])
    pr = state.read_run(run_dir).pr
    prs.set_ci(pr, "red", "lint: FAILURE")

    disk = FullDisk(monkeypatch, task="change")
    assert eng.run([RUN]).runs[RUN] == "retrying"
    assert _pending(run_dir).is_file()
    prs.set_ci(pr, "green", "")

    disk.full = False
    eng.run([RUN])
    run = state.read_run(run_dir)
    assert run.loops == {"verify->implement:ci": 1}
    assert _records(run_dir, "change") == ["001-verify-to-implement.json"]
    assert _types(run_dir).count("routed_back") == 1
    assert [c.task_id for c in worker.started].count("change") == 2  # the stage reran from the saved route
    assert not _pending(run_dir).exists()


def _pending(run_dir: Path) -> Path:
    return run_dir / "pending-route.json"


def test_a_gate_rework_whose_feedback_write_fails_is_still_routed_when_the_next_build_passes(outage):
    """The dropped case (module 8): the build fails, its record cannot be written, and the repeat pass finds a build that
    passes. The saved route is applied, and the build is not run again before the route."""
    run_dir, worker, eng, disk = outage
    gate = BuildFailsUntil(failures=1)  # the first build fails; every build after it passes

    with _gate(gate):
        assert eng.run([RUN]).runs[RUN] == "retrying"
        assert _pending(run_dir).is_file()
        disk.full = False
        assert eng.run([RUN]).runs[RUN] == "awaiting_approval"

    run = state.read_run(run_dir)
    # The gate runs once per task: the failing build for `a` (call 1), then `a` and `b` after the saved route reruns the
    # stage (calls 2 and 3). A dropped route gives the same count, so the route itself is what the next asserts check.
    assert gate.calls == 3
    assert run.loops == {"implement->implement": 1} and run.infra_wait is None
    assert _types(run_dir).count("routed_back") == 1
    assert _records(run_dir, "a") == ["001-implement-to-implement.json"]
    assert _records(run_dir, "b") == ["001-implement-to-implement.json"]
    assert [c.task_id for c in worker.started].count("a") == 2  # the stage reran from the saved route
    assert [c.task_id for c in worker.started].count("b") == 2
    assert not _pending(run_dir).exists()  # applied, so the saved route is gone


def test_a_saved_route_is_applied_once_however_many_passes_repeat_the_write(outage):
    run_dir, _worker, eng, disk = outage
    with _gate(BuildFailsUntil(failures=1)):
        assert eng.run([RUN]).runs[RUN] == "retrying"
        assert eng.run([RUN]).runs[RUN] == "retrying"  # the write still fails: the route is kept, not applied again
        assert state.read_run(run_dir).loops == {}
        assert json.loads(_pending(run_dir).read_text())["loop"] == 1
        disk.full = False
        assert eng.run([RUN]).runs[RUN] == "awaiting_approval"
    assert state.read_run(run_dir).loops == {"implement->implement": 1}  # moved once, not once per repeated pass
    assert _types(run_dir).count("routed_back") == 1


def test_a_saved_route_is_not_applied_to_a_wait_on_another_operation(outage):
    """A route left in the run folder (a crash between applying it and deleting the file) must not be applied when the
    run later waits on another operation, such as delivery. Only the feedback write's own wait applies a saved route."""
    run_dir, _worker, eng, disk = outage
    with _gate(BuildFailsUntil(failures=1)):
        assert eng.run([RUN]).runs[RUN] == "retrying"
    lock = state.acquire_lock(run_dir, "test")
    run = state.read_run(run_dir)
    run.infra_wait.last_error = "deliver: GitHub is unreachable"
    state.write_run(run_dir, run, lock=lock)
    state.release(lock)
    assert _pending(run_dir).is_file()  # the stale route is still in the folder

    disk.full = False
    with _gate(BuildFailsUntil(failures=0)):
        eng.run([RUN])
    assert "routed_back" not in _types(run_dir)  # the stale route was not applied to the delivery wait
    assert state.read_run(run_dir).loops == {}


def test_the_saved_route_names_the_routing_and_validates_against_its_schema(outage):
    run_dir, _worker, eng, _disk = outage
    with _gate(BuildFailsUntil(failures=1)):
        assert eng.run([RUN]).runs[RUN] == "retrying"
    doc = json.loads(_pending(run_dir).read_text())
    validate(doc, "pending-route", file=str(_pending(run_dir)))
    assert {k: doc[k] for k in ("from_stage", "goto", "reset", "loop", "max", "loop_key", "reason", "code", "tasks")} == {
        "from_stage": "implement", "goto": "implement", "reset": ["implement"], "loop": 1, "max": 3,
        "loop_key": "implement->implement", "reason": "implement failed its gate", "code": None, "tasks": ["a", "b"]}
    assert doc["feedback"]["to_stage"] == "implement" and doc["feedback"]["loop"] == 1


@pytest.mark.parametrize("text", ['{"goto": "implement"}', "not json"])
def test_a_malformed_pending_route_is_reported_and_not_ignored(outage, text):
    run_dir, _worker, eng, disk = outage
    with _gate(BuildFailsUntil(failures=1)):
        assert eng.run([RUN]).runs[RUN] == "retrying"
    _pending(run_dir).write_text(text)
    disk.full = False
    with pytest.raises(FactoryError) as raised:
        eng.run([RUN])
    assert raised.value.code == "config.invalid"
    assert _pending(run_dir).read_text() == text  # left as it is, for a person to read
    assert state.read_run(run_dir).loops == {}  # the route was not applied on a guess


def _pending_doc(**changes) -> dict:
    doc = {"schema_version": 1, "from_stage": "implement", "goto": "implement", "reset": ["implement"], "loop": 1,
           "max": 3, "loop_key": "implement->implement", "reason": "implement failed its gate", "code": None,
           "tasks": ["a", "b"],
           "feedback": {"schema_version": 1, "from_stage": "implement", "to_stage": "implement", "loop": 1, "max": 3,
                        "gate": "cmd: [make, build]", "exit_code": 1, "failed_tests": [], "output_tail": "build broke",
                        "changed_files": [], "at": "2026-11-25T10:00:00+08:00"}}
    doc.update(changes)
    return doc


def test_pending_route_dataclass_mirrors_its_schema():
    """AGENTS.md: the dataclass mirrors the state file's schema. The fields, and which of them are required, agree."""
    import dataclasses
    from factory_engine.rework import PendingRoute
    schema = json.loads((Path(rework.__file__).parents[2] / "schemas" / "pending-route.schema.json").read_text())
    fields = [f.name for f in dataclasses.fields(PendingRoute)]
    assert set(schema["properties"]) == {"schema_version", *fields}
    assert set(schema["required"]) == {"schema_version", *fields}
    assert schema["additionalProperties"] is False


def test_the_pending_route_schema_accepts_the_saved_shape_and_refuses_anything_else():
    validate(_pending_doc(), "pending-route")
    for bad in ({"loop": 0}, {"max": -1}, {"code": 7}, {"tasks": "a"}, {"surprise": 1}, {"schema_version": 2},
                {"feedback": {"gate": "cmd"}}):
        with pytest.raises(FactoryError):
            validate(_pending_doc(**bad), "pending-route")
    doc = _pending_doc()
    del doc["loop_key"]
    with pytest.raises(FactoryError):
        validate(doc, "pending-route")


def _fails_then_passes(counter: Path, fails: int, message: str) -> str:
    """A hook script that fails for its first `fails` runs and passes after that. `counter` holds the runs so far.
    A join commit runs its hook twice when the hook fails (gitops._commit_with_hook_retry retries once), so a join
    hook that fails once is retried and passes; `fails=2` is the join's first failing pass."""
    return (f"n=$(cat {counter} 2>/dev/null || echo 0); n=$((n+1)); echo $n > {counter}\n"
            f"if [ \"$n\" -le {fails} ]; then echo '{message}' >&2; exit 1; fi\nexit 0")


def test_a_join_hook_that_fails_once_then_passes_is_still_routed_back_when_its_write_fails(new_run, engine, repo, monkeypatch):
    """The join is one of the five rework routes. Its hook fails once, and the feedback write for that failure hits a
    disk error. The next pass finds the hook passing, and the saved route still sends the run back to `implement` with
    the hook's output in the record. The check is not run again to route it."""
    from test_repo_hooks_route import _install_hook, _plant_in_change
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * 4)
    eng, worker = engine(script, writes)
    _plant_in_change(worker, "services/new.py", "x = 2\n")
    _install_hook(repo, "pre-commit", _fails_then_passes(repo.parent / "join-hook-runs", 2, "lint: services/new.py line 1"))
    disk = FullDisk(monkeypatch, task="change")

    assert eng.run([RUN]).runs[RUN] == "retrying"
    assert json.loads(_pending(run_dir).read_text())["from_stage"] == "implement"
    assert state.read_run(run_dir).loops == {}

    disk.full = False
    eng.run([RUN])
    run = state.read_run(run_dir)
    assert run.loops == {"implement->implement": 1}  # routed once
    assert _types(run_dir).count("routed_back") == 1
    record = (run_dir / "tasks" / "change" / "feedback" / "001-implement-to-implement.json").read_text()
    assert "lint: services/new.py line 1" in record  # the hook's output reaches the worker, from the saved record
    assert not _pending(run_dir).exists()


def test_a_pre_push_hook_that_fails_once_then_passes_is_still_routed_back_when_its_write_fails(new_run, engine, repo, monkeypatch):
    """The pre-push hook is the fifth route, and it runs at delivery. The same drop: the hook fails, the write fails, and
    the next pass finds the hook passing. The saved route is still applied, and nothing reaches the remote before that."""
    from gitutil import ls_remote
    from test_repo_hooks_route import _install_hook, _plant_in_change
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * 4,
                                  check=[ok(work("check", "check.log"))] * 4)
    eng, worker = engine(script, writes)
    _plant_in_change(worker, "services/new.py", "x = 2\n")
    _install_hook(repo, "pre-push", _fails_then_passes(repo.parent / "push-hook-runs", 1, "pre-push: blocked by policy"))
    disk = FullDisk(monkeypatch, task="change")

    assert eng.run([RUN]).runs[RUN] == "retrying"
    assert not any(r == "refs/heads/bump-q1w2e" for r in ls_remote(repo))  # nothing pushed while the write waits
    disk.full = False
    eng.run([RUN])
    run = state.read_run(run_dir)
    assert len(run.loops) == 1 and list(run.loops.values()) == [1]  # one route, counted once
    assert _types(run_dir).count("routed_back") == 1
    record = sorted((run_dir / "tasks" / "change" / "feedback").glob("*.json"))[-1].read_text()
    assert "pre-push: blocked by policy" in record  # the hook's output reaches the worker, from the saved record
    assert not _pending(run_dir).exists()
