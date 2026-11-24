"""Module 6 `Engine.run` drives its runs at the same time, and module 3 `max_workers` caps the workers on the machine.

Each test holds its workers in `wait` until the test releases them, so "at the same time" is shown by the workers that
are running together, not by timing."""

import inspect
import threading
import time

import pytest

from concurrency_helpers import PerRunWorker, fan_script, settle, wait_until, write_fan_workflow
from factory_engine import state
from factory_engine.engine import Engine, EngineResult


def _engine(repo, cfg, tracker, prs, clock, worker) -> Engine:
    return Engine(repo, cfg, workers={"fake": worker}, command=worker, tracker=tracker, prs=prs, clock=clock)


def _start_together(eng: Engine, run_ids: list[str]) -> tuple[threading.Thread, dict]:
    """Start `eng.run(run_ids)` on a thread, with each run's triage done first so no git fetch runs at the same time."""
    box: dict = {}
    for rid in run_ids:
        eng.tick(rid)
    t = threading.Thread(target=lambda: box.update(result=eng.run(run_ids)), daemon=True)
    t.start()
    return t, box


def test_two_runs_make_progress_at_the_same_time(new_run, repo, cfg, tracker, prs, clock):
    ids, names = ["run-a", "run-b"], ["build"]
    write_fan_workflow(repo, names)
    runs = {rid: new_run(run_id=rid) for rid in ids}
    worker = PerRunWorker({rid: fan_script(runs[rid], names) for rid in ids},
                          hold={(rid, "build") for rid in ids})
    eng = _engine(repo, cfg, tracker, prs, clock, worker)
    t, box = _start_together(eng, ids)
    try:
        assert wait_until(lambda: len(worker.running) == 2, seconds=10), "the second run waited for the first"
    finally:
        worker.release_all()
        t.join(60)
    assert not t.is_alive() and set(box["result"].runs) == set(ids)
    assert all(state.read_run(runs[rid]).status == "awaiting_approval" for rid in ids)


def test_a_seventh_worker_waits_until_one_of_six_finishes(new_run, repo, cfg, tracker, prs, clock):
    names = [f"t{i}" for i in range(1, 8)]
    cfg.repo["concurrency"] = 10          # the repo cap is not what holds the seventh back
    write_fan_workflow(repo, names)
    run_dir = new_run(run_id="run-a")
    worker = PerRunWorker({"run-a": fan_script(run_dir, names)}, hold={("run-a", n) for n in names})
    eng = _engine(repo, cfg, tracker, prs, clock, worker)
    t, box = _start_together(eng, ["run-a"])
    try:
        assert wait_until(lambda: len(worker.running) == 6, seconds=10)
        settle(worker)                                    # give the engine the chance to start a seventh
        assert len(worker.running) == 6 and worker.peak == 6
        worker.release("run-a", "t1")                     # one worker ends, and the seventh may start
        assert wait_until(lambda: len(worker.running) == 6 and ("run-a", "t7") in worker.running, seconds=10)
        assert worker.peak == 6
    finally:
        worker.release_all()
        t.join(60)
    assert not t.is_alive() and box["result"].exit_code == 3


def test_max_workers_is_one_cap_for_all_the_runs_together(new_run, repo, cfg, tracker, prs, clock):
    ids, names = ["run-a", "run-b"], ["t1", "t2", "t3", "t4"]   # 4 + 4 ready tasks
    cfg.repo["concurrency"] = 10          # one repo's cap is not what holds them to six; the machine cap is
    write_fan_workflow(repo, names)
    runs = {rid: new_run(run_id=rid) for rid in ids}
    worker = PerRunWorker({rid: fan_script(runs[rid], names) for rid in ids},
                          hold={(rid, n) for rid in ids for n in names})
    eng = _engine(repo, cfg, tracker, prs, clock, worker)
    t, box = _start_together(eng, ids)
    try:
        assert wait_until(lambda: len(worker.running) == 6, seconds=10)
        settle(worker)
        assert len(worker.running) == 6 and worker.peak == 6    # eight are ready; six run on the machine
        assert {rid for rid, _ in worker.running} == set(ids)   # both runs have workers in the six
    finally:
        worker.release_all()
        t.join(60)
    assert worker.peak == 6 and not t.is_alive()


def test_the_exit_code_rule_holds_when_runs_are_driven_together(new_run, engine, monkeypatch):
    ids = ["r0", "r1", "r2", "r3"]
    statuses = {"r0": "done", "r1": "failed", "r2": "awaiting_approval", "r3": "done"}
    new_run()
    eng, _ = engine({})

    def drive(rid):
        import time as _t
        _t.sleep({"r0": 0.2, "r1": 0.0, "r2": 0.1, "r3": 0.05}[rid])   # the runs finish in a different order
        return statuses[rid]

    monkeypatch.setattr(eng, "_drive", drive)
    result: EngineResult = eng.run(ids)
    assert result.runs == statuses                           # in the order the runs were named
    assert list(result.runs) == ids
    assert result.exit_code == 3                             # a run waits on a person: 3, not the failure's 1


def test_a_run_that_raises_is_reraised_after_the_others_end(new_run, engine, monkeypatch):
    new_run()
    eng, _ = engine({})
    finished: list[str] = []

    def drive(rid):
        if rid == "boom":
            raise RuntimeError("the state write failed")
        time.sleep(0.2)
        finished.append(rid)
        return "done"

    monkeypatch.setattr(eng, "_drive", drive)
    with pytest.raises(RuntimeError, match="state write failed"):
        eng.run(["boom", "fine"])
    assert finished == ["fine"]                              # the other run still ran to its end


def test_concurrency_caps_one_repo_across_its_runs_together(new_run, repo, cfg, tracker, prs, clock):
    """`concurrency` caps one repo, so two runs of that repo share it: 2 workers at once, not 2 for each run."""
    ids, names = ["run-a", "run-b"], ["t1", "t2", "t3"]
    cfg.repo["concurrency"] = 2
    write_fan_workflow(repo, names)
    runs = {rid: new_run(run_id=rid) for rid in ids}
    worker = PerRunWorker({rid: fan_script(runs[rid], names) for rid in ids},
                          hold={(rid, n) for rid in ids for n in names})
    eng = _engine(repo, cfg, tracker, prs, clock, worker)
    t, box = _start_together(eng, ids)
    try:
        assert wait_until(lambda: len(worker.running) == 2, seconds=10)
        settle(worker)
        assert len(worker.running) == 2 and worker.peak == 2
    finally:
        worker.release_all()
        t.join(60)
    assert worker.peak == 2 and not t.is_alive()


def test_resume_has_no_force_parameter(new_run, engine):
    assert "force" not in inspect.signature(Engine.resume).parameters
    new_run()
    eng, _ = engine({})
    with pytest.raises(TypeError):
        eng.resume("bump-q1w2e", force=True)
