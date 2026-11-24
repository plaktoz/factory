"""A rework's feedback write that fails partway is retried on the next tick (owner decision, 2026-11-24): a retry
leaves each task folder with exactly one copy of the record, and no record is written twice."""

from unittest import mock

import pytest

from factory_engine import rework


def _tasks(tmp_path, names):
    for t in names:
        (tmp_path / "tasks" / t / "work").mkdir(parents=True)
    return tmp_path


def _records(run_dir, task):
    return sorted(p.name for p in (run_dir / "tasks" / task / "feedback").glob("*.json"))


def _fail_on_call(n, real):
    calls = {"n": 0}

    def write(path, doc):
        calls["n"] += 1
        if calls["n"] == n:
            raise OSError("disk full")
        return real(path, doc)

    return write


def test_a_retry_after_a_partial_write_leaves_one_record_per_task(tmp_path):
    run_dir = _tasks(tmp_path, ["a", "b"])
    real = rework.write_json_atomic
    args = dict(from_stage="propose", to_stage="root-cause", notes="tighten it", loop=1, max_loops=3, task_ids=["a", "b"])

    with mock.patch.object(rework, "write_json_atomic", _fail_on_call(2, real)):
        with pytest.raises(OSError):
            rework.build_human_feedback(run_dir, **args)
    rework.build_human_feedback(run_dir, **args)

    assert _records(run_dir, "a") == ["001-propose-to-root-cause.json"]
    assert _records(run_dir, "b") == ["001-propose-to-root-cause.json"]


def test_a_retry_rewrites_nothing_that_was_already_written(tmp_path):
    run_dir = _tasks(tmp_path, ["a", "b"])
    real = rework.write_json_atomic
    args = dict(from_stage="propose", to_stage="root-cause", notes="tighten it", loop=1, max_loops=3, task_ids=["a", "b"])
    with mock.patch.object(rework, "write_json_atomic", _fail_on_call(2, real)):
        with pytest.raises(OSError):
            rework.build_human_feedback(run_dir, **args)
    first = (run_dir / "tasks" / "a" / "feedback" / "001-propose-to-root-cause.json").read_bytes()
    rework.build_human_feedback(run_dir, **args)
    assert (run_dir / "tasks" / "a" / "feedback" / "001-propose-to-root-cause.json").read_bytes() == first
