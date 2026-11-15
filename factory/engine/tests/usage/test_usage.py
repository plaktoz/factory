"""Module 14 acceptance criteria."""

from datetime import date
from pathlib import Path

import pytest

from factory_engine import usage
from factory_engine.errors import FactoryError
from factory_engine.lock import acquire_lock, release
from factory_engine.state import init_run
from factory_engine.types import Request, Source, TaskState
from factory_engine import state


def make(tmp_path, run_id="run-1", repo="report", key="github.com/acme/report"):
    src = Source("github", "acme/report#1", "t", "b", [], "a", [])
    rq = Request("gh-1", src, "sha", repo, "t", "bug", "label", "high", [])
    repo_path = tmp_path / repo
    repo_path.mkdir(exist_ok=True)
    ref = init_run(tmp_path / "home", repo_path, key, run_id, rq, branch=run_id, worktree=tmp_path / "wt", kit_hash="x")
    run = state.read_run(ref.run_dir)
    lock = acquire_lock(ref.run_dir, "e")
    state.write_task(ref.run_dir, TaskState("backend", "fix", "running", 1, 0, None, None, 0), lock=lock)
    release(lock)
    return ref.run_dir, run


def records(run_dir, task="backend"):
    from factory_engine.atomic import read_jsonl
    return read_jsonl(run_dir / "tasks" / task / "usage.jsonl")


def test_a_started_record_exists_before_the_worker_launches_and_the_ended_record_holds_the_facts(tmp_path):
    run_dir, run = make(tmp_path)
    n = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested="claude-opus-5-5")
    assert [r["exit"] for r in records(run_dir)] == ["started"]   # written before any finish call
    usage.finish_attempt(run_dir, "backend", n, exit="ok", input_tokens=100, output_tokens=40, models=["claude-opus-5-5"])
    last = records(run_dir)[-1]
    assert last["model_requested"] == "claude-opus-5-5"  # the ended record keeps the requested model
    assert last["exit"] == "ok" and last["models"] == ["claude-opus-5-5"]
    assert last["repo"] == "report" and last["branch"] == "run-1" and last["worktree"] == str(tmp_path / "wt")
    assert last["input_tokens"] == 100 and last["output_tokens"] == 40 and last["total_tokens"] == 140
    assert last["start"] and last["end"] and last["run_id"] == "run-1" and last["stage"] == "fix"


def test_the_last_line_for_an_attempt_wins_and_attempts_are_numbered(tmp_path):
    run_dir, run = make(tmp_path)
    a1 = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", a1, exit="failed", input_tokens=None, output_tokens=None, models=[])
    a2 = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    assert (a1, a2) == (1, 2)
    recs = usage.read_usage(run_dir, "backend")
    assert [(r.attempt, r.exit) for r in recs] == [(1, "failed"), (2, "started")]


def test_a_requested_model_is_recorded_and_no_request_gives_null(tmp_path):
    run_dir, run = make(tmp_path)
    usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    assert records(run_dir)[0]["model_requested"] is None
    usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested="claude-opus-5-5")
    assert records(run_dir)[1]["model_requested"] == "claude-opus-5-5"


def test_an_attempt_with_no_requested_model_records_the_observed_models_from_the_result(tmp_path):
    run_dir, run = make(tmp_path)
    n = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", n, exit="ok", input_tokens=5, output_tokens=5, models=["claude-advantage-assist"])
    r = usage.read_usage(run_dir, "backend")[0]
    assert r.model_requested is None and r.models == ["claude-advantage-assist"]


def test_unknown_tokens_are_null_never_zero_and_counted_separately(tmp_path):
    run_dir, run = make(tmp_path)
    n = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", n, exit="ok", input_tokens=None, output_tokens=None, models=["m"])
    r = usage.read_usage(run_dir, "backend")[0]
    assert r.input_tokens is None and r.output_tokens is None and r.total_tokens is None
    rep = usage.summarize([run_dir])
    assert rep.by_model["m"].attempts_without_count == 1 and rep.by_model["m"].total_tokens == 0


def test_close_open_attempts_marks_every_open_attempt_interrupted_with_no_count(tmp_path):
    run_dir, run = make(tmp_path)
    make_second = make(tmp_path, "run-1b", repo="report2", key="github.com/acme/report2")
    usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    done = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", done, exit="ok", input_tokens=1, output_tokens=1, models=["m"])
    closed = usage.close_open_attempts(run_dir)
    assert closed == [("backend", 1), ("backend", 2)]
    recs = {r.attempt: r for r in usage.read_usage(run_dir, "backend")}
    assert recs[1].exit == recs[2].exit == "interrupted" and recs[1].input_tokens is None and recs[3].exit == "ok"


def test_reports_group_by_observed_model_repo_and_day_with_unknown_for_no_model(tmp_path):
    run_dir, run = make(tmp_path)
    n = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", n, exit="ok", input_tokens=10, output_tokens=5, models=["opus"])
    n2 = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", n2, exit="ok", input_tokens=2, output_tokens=2, models=[])
    rep = usage.summarize([run_dir])
    assert rep.by_model["opus"].total_tokens == 15 and rep.by_model["opus"].attempts == 1
    assert rep.by_model["unknown"].attempts == 1 and rep.by_model["unknown"].total_tokens == 4
    assert rep.by_repo["report"].attempts == 2
    today = run.request and records(run_dir)[0]["start"][:10]
    assert rep.by_day[today].attempts == 2


def test_an_attempt_with_several_models_is_counted_under_each(tmp_path):
    run_dir, run = make(tmp_path)
    n = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", n, exit="ok", input_tokens=10, output_tokens=0, models=["a", "b"])
    rep = usage.summarize([run_dir])
    assert rep.by_model["a"].attempts == 1 and rep.by_model["b"].attempts == 1


def test_an_open_attempt_is_not_counted_in_a_report(tmp_path):
    run_dir, run = make(tmp_path)
    usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    assert usage.summarize([run_dir]).by_model == {}


def test_a_bad_exit_value_is_refused(tmp_path):
    run_dir, run = make(tmp_path)
    n = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    with pytest.raises(FactoryError, match="not one of"):
        usage.finish_attempt(run_dir, "backend", n, exit="maybe", input_tokens=None, output_tokens=None, models=[])


def test_a_started_record_is_schema_valid(tmp_path):
    from factory_engine.validate import validate
    run_dir, run = make(tmp_path)
    usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    doc = dict(records(run_dir)[0])
    validate(doc, "usage")
