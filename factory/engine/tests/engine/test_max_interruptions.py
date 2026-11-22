"""Module 8, engine crash: a task cut off `max_interruptions` times is failed, and each task is judged by its own value.

The engine is cut off the way a kill leaves it: the attempt's `started` usage record is open, the lock is free, and
nothing after that point ran. `Crash` is a BaseException raised where the engine records the worker's result, so
nothing in the engine can catch it. (The kill of a real child process is `test_kill_the_engine_mid_task_then_resume`.)
"""

import json

import pytest

from factory_engine import state, usage
from factory_engine.adapters.worker.fake import ok
from factory_engine.errors import FactoryError

from engine_helpers import TRIAGE_JSON, chore_script


class Crash(BaseException):
    """The engine process dies here."""


def _cut_off(eng, run_id: str, *, first: bool, tasks: tuple[str, ...] = ("change",)) -> None:
    """Drive (the first time) or resume (after that) the run, and kill the engine when one of `tasks` records a result."""
    real = eng._record_result

    def die(run_dir, lock, job, result):
        if job.spec.id not in tasks:
            return real(run_dir, lock, job, result)
        raise Crash

    eng._record_result = die
    try:
        with pytest.raises(Crash):
            eng.run([run_id]) if first else eng.resume(run_id)
    finally:
        eng._record_result = real


def _cut_off_n_times(eng, run_id: str, n: int, tasks: tuple[str, ...] = ("change",)) -> None:
    for i in range(n):
        _cut_off(eng, run_id, first=i == 0, tasks=tasks)


def _exits(run_dir, task_id: str) -> list[str]:
    return [r.exit for r in usage.read_usage(run_dir, task_id)]


def _set_change_task(eng, replacement: str) -> None:
    """Replace the head of the shipped chore workflow's `change` task, in the repo's own workflow folder."""
    wf_dir = eng.repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    chore = (eng.repo / "factory" / "workflows" / "chore.yaml").read_text()
    changed = chore.replace("{id: change, skill: implement,", replacement, 1)
    assert changed != chore
    (wf_dir / "chore.yaml").write_text(changed)


def _chore(new_run, engine, attempts: int):
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * attempts)
    eng, worker = engine(script, writes)
    return run_dir, eng, worker


def test_with_the_default_two_interruptions_still_resume_and_the_third_attempt_finishes(new_run, engine):
    run_dir, eng, worker = _chore(new_run, engine, attempts=3)
    _cut_off_n_times(eng, "bump-q1w2e", 2)
    eng.resume("bump-q1w2e")
    assert _exits(run_dir, "change") == ["interrupted", "interrupted", "ok"]
    assert state.read_task(run_dir, "change").status == "done"
    assert state.read_run(run_dir).status == "awaiting_approval"      # the run went on to its pull request


@pytest.mark.parametrize("explicit", [None, 3], ids=["default", "explicit-3"])
def test_the_third_interruption_fails_the_task_and_no_fourth_attempt_starts(new_run, engine, capsys, explicit):
    from factory_engine import cli
    run_dir, eng, worker = _chore(new_run, engine, attempts=4)
    if explicit is not None:
        _set_change_task(eng, f"{{id: change, skill: implement, max_interruptions: {explicit},")
    _cut_off_n_times(eng, "bump-q1w2e", 3)
    eng.resume("bump-q1w2e")
    assert state.read_task(run_dir, "change").status == "failed"
    assert _exits(run_dir, "change") == ["interrupted"] * 3            # no attempt 4
    assert sum(1 for c in worker.started if c.task_id == "change") == 3
    run = state.read_run(run_dir)
    assert run.status == "blocked" and run.attention is not None and run.attention.kind == "blocked"
    capsys.readouterr()
    assert cli.main(["status", "bump-q1w2e", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)["data"]["runs"][0]
    assert shown["status"] == "blocked" and shown["attention"]["kind"] == "blocked"


def test_a_failed_task_is_not_retried_by_another_resume(new_run, engine):
    run_dir, eng, worker = _chore(new_run, engine, attempts=4)
    _cut_off_n_times(eng, "bump-q1w2e", 3)
    eng.resume("bump-q1w2e")
    started = len(worker.started)  # the failed task's resume must not start it again
    eng.resume("bump-q1w2e")
    assert len(worker.started) == started and state.read_task(run_dir, "change").status == "failed"


def test_the_cap_is_the_tasks_own_max_interruptions(new_run, engine):
    run_dir, eng, worker = _chore(new_run, engine, attempts=2)
    _set_change_task(eng, "{id: change, skill: implement, max_interruptions: 1,")
    _cut_off(eng, "bump-q1w2e", first=True)
    eng.resume("bump-q1w2e")
    assert state.read_task(run_dir, "change").status == "failed"
    assert _exits(run_dir, "change") == ["interrupted"]


def test_max_interruptions_0_fails_the_task_at_its_first_crash(new_run, engine):
    run_dir, eng, worker = _chore(new_run, engine, attempts=2)
    _set_change_task(eng, "{id: change, skill: implement, max_interruptions: 0,")
    _cut_off(eng, "bump-q1w2e", first=True)
    eng.resume("bump-q1w2e")
    assert state.read_task(run_dir, "change").status == "failed"
    assert sum(1 for c in worker.started if c.task_id == "change") == 1


TWO_TASKS = """name: chore
type: chore
sink: pull_request
policy: {write: true, deny_paths: []}
defaults: {retries: 2, timeout_minutes: 30, checkpoint_every_minutes: 10, max_restarts: 3}
stages:
  - id: work
    tasks:
      - {id: low, cmd: [/usr/bin/true], max_interruptions: 2, out: low.json}
      - {id: high, cmd: [/usr/bin/true], out: high.json}
"""


def test_two_tasks_cut_off_the_same_number_of_times_are_each_judged_by_their_own_value(new_run, engine):
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))],
              "low": [ok(work("low", "low.json"))] * 3, "high": [ok(work("high", "high.json"))] * 3}
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "low": {"low.json": "{}"}, "high": {"high.json": "{}"}}
    eng, worker = engine(script, writes)
    wf_dir = eng.repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "chore.yaml").write_text(TWO_TASKS)
    _cut_off_n_times(eng, "bump-q1w2e", 2, tasks=("low", "high"))      # both tasks run together, and both are cut off twice
    assert _exits(run_dir, "low") == _exits(run_dir, "high") == ["interrupted", "started"]  # the 2nd crash cut off attempt 2
    eng.resume("bump-q1w2e")                                            # closes attempt 2: each task has 2 interruptions
    assert _exits(run_dir, "low") == ["interrupted", "interrupted"]
    assert state.read_task(run_dir, "low").status == "failed"          # its own limit is 2
    # `low` failed for good, so module 8 starts no new task: `high` keeps its 2 interruptions and is not failed,
    # because its own limit (the default, 3) is not reached. With limit 2 on `high`, it would be failed.
    assert _exits(run_dir, "high") == ["interrupted", "interrupted"]
    assert state.read_task(run_dir, "high").status == "interrupted"


def test_a_negative_or_non_integer_value_is_refused_when_the_workflow_loads(new_run, engine):
    _, eng, _ = _chore(new_run, engine, attempts=1)
    for bad in ("-1", "1.5", "'3'"):
        _set_change_task(eng, "{id: change, skill: implement, max_interruptions: %s," % bad)
        with pytest.raises(FactoryError) as e:
            eng._load("chore")
        assert e.value.code == "config.invalid" and "max_interruptions" in e.value.message
