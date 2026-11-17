"""Module 8 blocked-run actions, as module 16 drivers: retry, goto and skip, run against the real engine.

Module 8: `factory retry` runs the stage once more with the note added to the feedback; `factory goto` routes to an
earlier stage; `factory skip --gate` passes only a gate marked `skippable: true`, logs the skip and stops auto-merge.
Each action is a driver. It takes the run's lock, changes the run, and starts no worker itself.
"""

from pathlib import Path

import pytest

from engine_fixtures import chore_script  # noqa: E402

from factory_engine import api, delivery, state  # noqa: E402
from factory_engine.adapters.worker.fake import failed  # noqa: E402
from factory_engine.config import Config  # noqa: E402
from factory_engine.errors import FactoryError  # noqa: E402
from factory_engine.workflow import load_workflow  # noqa: E402

KIT = Path(__file__).resolve().parents[3]  # factory/


def write_workflow(repo: Path, name: str, gate_line: str) -> None:
    wf_dir = repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / f"{name}.yaml").write_text(
        f"name: {name}\ntype: chore\nsink: pull_request\nstages:\n"
        "  - id: check\n    tasks: [{id: t, cmd: [echo, ok]}]\n"
        f"    gate: [{gate_line}]\n")


def make_implement_gate_skippable(repo: Path) -> None:
    """A project's own `chore`: the shipped one, with `lint-clean` marked skippable on the `implement` stage."""
    wf_dir = repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    text = (KIT / "workflows" / "chore.yaml").read_text()
    assert "{check: lint-clean}" in text
    (wf_dir / "chore.yaml").write_text(text.replace("{check: lint-clean}", "{check: lint-clean, skippable: true}"))


def blocked_chore_run(new_run, engine):
    """Drive the chore run until its `change` task fails past its retries, which blocks the run."""
    run_dir = new_run()
    script, writes = chore_script(run_dir, change=[failed("crash")] * 3)
    eng, _ = engine(script, writes)
    eng.run(["bump-q1w2e"])
    assert state.read_run(run_dir).status == "blocked"
    return run_dir, eng


# ---- the skippable flag -----------------------------------------------------------------------------------------

def test_a_gate_marked_skippable_loads_as_skippable_and_the_others_stay_strict(repo):
    write_workflow(repo, "flagged", "{cmd: [make, lint], skippable: true}, {cmd: [make, test]}")
    lint, test = load_workflow(repo, Config(machine={}, repo={}), "flagged").stages[0].gate
    assert lint.skippable is True
    assert test.skippable is False


def test_skippable_must_be_a_boolean(repo):
    write_workflow(repo, "bad", "{cmd: [make, lint], skippable: yes-please}")
    with pytest.raises(FactoryError) as e:
        load_workflow(repo, Config(machine={}, repo={}), "bad")
    assert e.value.code == "config.invalid"


def test_no_shipped_gate_is_skippable():
    """The shipped workflows keep every gate strict. A project opts a gate in with its own workflow."""
    import yaml
    for path in (KIT / "workflows").glob("*.yaml"):
        doc = yaml.safe_load(path.read_text())
        for stage in doc.get("stages", []):
            for gate in stage.get("gate") or []:
                assert not gate.get("skippable"), f"{path.name}: stage {stage['id']} marks a gate skippable"


# ---- skip ---------------------------------------------------------------------------------------------------------

def test_skip_refuses_a_gate_the_workflow_did_not_mark_skippable(new_run, engine):
    run_dir, eng = blocked_chore_run(new_run, engine)
    with pytest.raises(FactoryError) as e:
        api.skip(eng.repo, "bump-q1w2e", "lint-clean", reason="needed for the demo")
    assert e.value.code == "config.invalid" and "not marked skippable" in e.value.message
    assert state.read_run(run_dir).status == "blocked"
    assert not [ev for ev in state.read_events(run_dir) if ev.type == "gate_skipped"]


def test_skip_passes_a_skippable_gate_logs_the_reason_and_blocks_auto_merge(new_run, engine):
    run_dir, eng = blocked_chore_run(new_run, engine)
    make_implement_gate_skippable(eng.repo)
    api.skip(eng.repo, "bump-q1w2e", "lint-clean", reason="flaky on CI, tracked in #77")
    skipped = [ev for ev in state.read_events(run_dir) if ev.type == "gate_skipped"]
    assert len(skipped) == 1
    assert skipped[0].data["gate"] == "lint-clean" and skipped[0].data["stage"] == "implement"
    assert skipped[0].data["reason"] == "flaky on CI, tracked in #77"
    assert state.read_run(run_dir).status != "blocked"
    decision = delivery.evaluate_merge(run_dir, eng.cfg, changed=[], ci="green")
    gates_rule = next(r for r in decision.rules if r.rule == "auto.require.gates")
    assert gates_rule.passed is False


def test_skip_needs_a_reason(new_run, engine):
    run_dir, eng = blocked_chore_run(new_run, engine)
    make_implement_gate_skippable(eng.repo)
    with pytest.raises(FactoryError) as e:
        api.skip(eng.repo, "bump-q1w2e", "lint-clean", reason="   ")
    assert e.value.code == "config.invalid"
    assert state.read_run(run_dir).status == "blocked"


# ---- retry --------------------------------------------------------------------------------------------------------

def test_retry_queues_the_note_and_moves_the_blocked_run_back_to_running(new_run, engine):
    run_dir, eng = blocked_chore_run(new_run, engine)
    loops_before = dict(state.read_run(run_dir).loops)
    assert state.read_task(run_dir, "change").status == "failed"
    api.retry(eng.repo, "bump-q1w2e", note="the lockfile was stale; regenerate it")
    run = state.read_run(run_dir)
    assert run.status == "running" and run.attention is None
    assert run.loops == loops_before
    assert state.read_task(run_dir, "change").status == "pending"
    queued = [ev for ev in state.read_events(run_dir) if ev.type == "note_queued"]
    assert queued and queued[-1].data["task_id"] == "change"


def test_retry_without_a_note_queues_nothing(new_run, engine):
    run_dir, eng = blocked_chore_run(new_run, engine)
    api.retry(eng.repo, "bump-q1w2e")
    assert state.read_run(run_dir).status == "running"
    assert not [ev for ev in state.read_events(run_dir) if ev.type == "note_queued"]


def test_retry_refuses_a_run_that_is_not_blocked(new_run, engine):
    new_run()
    eng, _ = engine({}, {})
    with pytest.raises(FactoryError) as e:
        api.retry(eng.repo, "bump-q1w2e")
    assert e.value.code == "config.invalid"
    assert "not blocked" in e.value.message


# ---- goto ---------------------------------------------------------------------------------------------------------

def test_goto_routes_a_blocked_run_to_an_earlier_stage_and_resets_it(new_run, engine):
    run_dir, eng = blocked_chore_run(new_run, engine)
    api.goto(eng.repo, "bump-q1w2e", "implement")
    run = state.read_run(run_dir)
    assert run.status == "running" and run.stage == "implement"
    assert {s.id: s.status for s in run.stages}["implement"] == "pending"


def test_goto_refuses_a_stage_the_workflow_does_not_have(new_run, engine):
    run_dir, eng = blocked_chore_run(new_run, engine)
    with pytest.raises(FactoryError) as e:
        api.goto(eng.repo, "bump-q1w2e", "no-such-stage")
    assert e.value.code == "config.invalid"
    assert state.read_run(run_dir).status == "blocked"
