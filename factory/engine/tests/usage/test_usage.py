"""Module 14 acceptance criteria."""

import json
from datetime import date
from pathlib import Path

import pytest

from factory_engine import api, cli, usage
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


def write_raw(run_dir, data: bytes, task="backend"):
    """Append bytes straight to a task's usage file, to put a damaged line in it."""
    with (run_dir / "tasks" / task / "usage.jsonl").open("ab") as fh:
        fh.write(data)


def set_times(run_dir, attempt, start, end=None, task="backend"):
    """Rewrite the times on every line of one attempt, so days and minutes can be checked without waiting."""
    path = run_dir / "tasks" / task / "usage.jsonl"
    docs = [json.loads(line) for line in path.read_text().splitlines()]
    for d in docs:
        if d["attempt"] == attempt:
            d["start"] = start
            if end is not None:
                d["end"] = end
    path.write_text("".join(json.dumps(d, separators=(",", ":")) + "\n" for d in docs))


def unreadable_events(run_dir):
    return [e.data for e in state.read_events(run_dir) if e.type == "usage_unreadable"]


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
    assert rep.by_model["a"].total_tokens == 10 and rep.by_model["b"].total_tokens == 10
    set_times(run_dir, n, "2020-01-02T10:00:00+00:00", "2020-01-02T10:30:00+00:00")
    rep = usage.summarize([run_dir])
    assert rep.by_model["a"].minutes == 30.0 and rep.by_model["b"].minutes == 30.0


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


# ---- fixes after the 2026-11-21 probe ------------------------------------------------------------------------------

def test_a_line_with_no_attempt_number_is_skipped_and_the_read_goes_on(tmp_path):
    run_dir, run = make(tmp_path)
    usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    write_raw(run_dir, b'{"schema_version":1,"run_id":"run-1","exit":"ok"}\n')
    recs = usage.read_usage(run_dir, "backend")
    assert [(r.attempt, r.exit) for r in recs] == [(1, "started")]
    assert usage.close_open_attempts(run_dir) == [("backend", 1)]


def test_a_record_after_a_torn_line_starts_on_a_new_line_and_its_attempt_finishes(tmp_path):
    run_dir, run = make(tmp_path)
    usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    n1 = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", n1, exit="ok", input_tokens=1, output_tokens=1, models=["m"])
    write_raw(run_dir, b'{"schema_version":1,"run_id":"run-1","attempt":3,"exit":"ok"')  # cut off: no newline
    n = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", n, exit="ok", input_tokens=2, output_tokens=2, models=["m"])
    recs = {r.attempt: r for r in usage.read_usage(run_dir, "backend")}
    assert recs[n].exit == "ok" and recs[n].total_tokens == 4


def test_an_unreadable_last_line_does_not_hide_an_earlier_whole_line_for_the_attempt(tmp_path):
    run_dir, run = make(tmp_path)
    n = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", n, exit="ok", input_tokens=4, output_tokens=4, models=["m"])
    write_raw(run_dir, b'{"attempt":1,"exit":"failed"}\n')  # whole line, but missing fields
    recs = usage.read_usage(run_dir, "backend")
    assert [(r.attempt, r.exit, r.total_tokens) for r in recs] == [(1, "ok", 8)]


def test_finish_after_an_unreadable_line_uses_the_attempts_started_record(tmp_path):
    run_dir, run = make(tmp_path)
    n = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    write_raw(run_dir, b'{"attempt":1,"exit":"failed"}\n')  # whole line, but missing fields
    usage.finish_attempt(run_dir, "backend", n, exit="ok", input_tokens=4, output_tokens=4, models=["m"])
    recs = usage.read_usage(run_dir, "backend")
    assert [(r.attempt, r.exit, r.total_tokens) for r in recs] == [(1, "ok", 8)]


def test_start_attempt_does_not_reuse_a_number_seen_in_an_unreadable_line(tmp_path):
    run_dir, run = make(tmp_path)
    usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    write_raw(run_dir, b'{"attempt":2,"run_id":"run-1"}\n')  # attempt 2 is readable, the rest is not
    assert usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None) == 3


def test_start_attempt_writes_one_usage_unreadable_event_per_line_with_the_task_and_line(tmp_path):
    run_dir, run = make(tmp_path)
    usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    write_raw(run_dir, b'{"schema_version":1,"run_id":"run-1","attempt":1,"exit":"ok"')  # line 2, cut off
    usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    assert unreadable_events(run_dir) == [{"task_id": "backend", "line": 2}]


def test_read_paths_write_no_events(tmp_path):
    run_dir, run = make(tmp_path)
    usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    write_raw(run_dir, b'{"torn')
    before = [e.type for e in state.read_events(run_dir)]
    usage.read_usage(run_dir, "backend")
    usage.summarize([run_dir])
    assert [e.type for e in state.read_events(run_dir)] == before
    assert unreadable_events(run_dir) == []


def test_the_total_counts_an_attempt_with_several_models_once(tmp_path):
    run_dir, run = make(tmp_path)
    n = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", n, exit="ok", input_tokens=10, output_tokens=0, models=["a", "b"])
    n2 = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", n2, exit="ok", input_tokens=3, output_tokens=3, models=[])
    rep = usage.summarize([run_dir])
    assert rep.by_model["a"].total_tokens == 10 and rep.by_model["b"].total_tokens == 10
    assert rep.total.attempts == 2 and rep.total.total_tokens == 16 and rep.total.attempts_without_count == 0


def test_a_report_with_since_leaves_out_attempts_that_start_before_that_day(tmp_path):
    run_dir, run = make(tmp_path)
    for _ in range(2):
        n = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
        usage.finish_attempt(run_dir, "backend", n, exit="ok", input_tokens=1, output_tokens=1, models=["m"])
    set_times(run_dir, 1, "2020-01-02T10:00:00+00:00")
    assert usage.summarize([run_dir], since=date(2021, 1, 1)).by_repo["report"].attempts == 1
    assert usage.summarize([run_dir]).by_repo["report"].attempts == 2


def test_factory_usage_labels_the_model_rows_and_prints_the_total(tmp_path, capsys, monkeypatch):
    run_dir, run = make(tmp_path)
    n = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", n, exit="ok", input_tokens=10, output_tokens=0, models=["a", "b"])
    monkeypatch.setattr(api, "usage", lambda repo, run_id=None, since=None: usage.summarize([run_dir]))
    code = cli.main(["usage", "--repo", str(tmp_path / "report")])
    out = capsys.readouterr().out
    assert code == 0
    assert "per model, an attempt with several models is counted under each" in out
    assert "a: 1 attempt, 10 tokens" in out and "b: 1 attempt, 10 tokens" in out
    assert "total, each attempt counted once" in out


def test_factory_usage_json_carries_the_total(tmp_path, capsys, monkeypatch):
    run_dir, run = make(tmp_path)
    n = usage.start_attempt(run_dir, run, "backend", stage="fix", harness="claude", model_requested=None)
    usage.finish_attempt(run_dir, "backend", n, exit="ok", input_tokens=10, output_tokens=0, models=["a", "b"])
    monkeypatch.setattr(api, "usage", lambda repo, run_id=None, since=None: usage.summarize([run_dir]))
    cli.main(["usage", "--repo", str(tmp_path / "report"), "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["data"]["total"]["attempts"] == 1 and doc["data"]["total"]["total_tokens"] == 10
