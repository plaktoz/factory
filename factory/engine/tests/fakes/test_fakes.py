"""W0.5: each fake can script success and failure, and satisfies the protocol other modules code against."""

import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from factory_engine.adapters.tracker.base import TrackerAdapter
from factory_engine.adapters.tracker.fake import FakeTracker
from factory_engine.adapters.worker.base import (AttemptResult, Capabilities, HarnessConfig, SkillRef,
                                                 TaskContext, WorkerAdapter)
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, failed, ok, timeout
from factory_engine.clock import FakeClock, SystemClock
from factory_engine.fake_prs import FakePullRequests
from factory_engine.prs import PullRequests
from factory_engine.types import Clock, HelperPolicy, PrRef, Request, Source


def public_methods(proto):
    return {n for n, m in inspect.getmembers(proto, inspect.isfunction) if not n.startswith("_")}


def assert_satisfies(obj, proto):
    """Every protocol method exists on obj with the same parameter names."""
    for name in public_methods(proto):
        assert hasattr(obj, name), f"{type(obj).__name__} lacks {name}"
        want = [p for p in inspect.signature(getattr(proto, name)).parameters if p != "self"]
        have = [p for p in inspect.signature(getattr(obj, name)).parameters]
        assert have == want, f"{name}: {have} != {want}"


# ---- FakeClock ----

def test_fake_clock_implements_clock():
    assert_satisfies(FakeClock(), Clock)
    assert_satisfies(SystemClock(), Clock)


def test_fake_clock_does_not_move_on_its_own_and_sleep_advances_it():
    c = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert c.now() == c.now()
    c.sleep(30)
    c.sleep(120)
    assert c.now() == datetime(2026, 1, 1, 0, 2, 30, tzinfo=timezone.utc)
    assert c.sleeps == [30, 120]


def test_fake_clock_advance_and_negative_sleep_refused():
    c = FakeClock()
    t0 = c.now()
    c.advance(3600)
    assert c.now() - t0 == timedelta(hours=1)
    with pytest.raises(ValueError):
        c.sleep(-1)


# ---- FakeWorkerAdapter ----

def ctx(tmp_path, task_id="backend", attempt=1) -> TaskContext:
    src = Source("cli", "r", "t", "b", [], None, [])
    req = Request("r1", src, "sha", "repo", "t", "bug", "explicit", None, [])
    skill = SkillRef("fix", "own", tmp_path, {})
    return TaskContext("run1", task_id, "fix", attempt, skill, req, tmp_path, tmp_path / "work", [], [],
                       HelperPolicy("off", 0, [], None), [], [], None, None, None, [], [])


CONF = HarnessConfig("fake", None, [], {})


def test_worker_fake_satisfies_the_adapter_protocol():
    assert_satisfies(FakeWorkerAdapter({}), WorkerAdapter)
    assert FakeWorkerAdapter({}).capabilities == Capabilities("none", True)


def test_worker_fake_scripts_success_then_failure_then_timeout(tmp_path):
    f = FakeWorkerAdapter({"backend": [ok(models=["m1"]), failed("rate_limit"), timeout()]})
    results = []
    for n in (1, 2, 3):
        h = f.start(ctx(tmp_path, attempt=n), CONF, tmp_path / "worker.log")
        results.append(f.wait(h, 60))
    assert [r.exit for r in results] == ["ok", "failed", "timeout"]
    assert results[0].models_observed == ["m1"] and results[0].error_kind is None
    assert results[1].error_kind == "rate_limit" and results[1].exit_code == 1
    assert results[2].exit_code is None


def test_worker_fake_writes_artifact_contents_per_task(tmp_path):
    f = FakeWorkerAdapter({"backend": [ok()]}, writes={"backend": {"backend.json": '{"x": 1}', "sub/progress.md": "step 2"}})
    c = ctx(tmp_path)
    f.start(c, CONF, tmp_path / "worker.log")
    assert (c.task_dir / "backend.json").read_text() == '{"x": 1}'
    assert (c.task_dir / "sub" / "progress.md").read_text() == "step 2"
    assert (tmp_path / "worker.log").exists()


def test_worker_fake_refuses_an_attempt_that_was_not_scripted(tmp_path):
    f = FakeWorkerAdapter({"backend": [ok()]})
    f.start(ctx(tmp_path), CONF, tmp_path / "l")
    with pytest.raises(AssertionError, match="no scripted attempt 2"):
        f.start(ctx(tmp_path, attempt=2), CONF, tmp_path / "l")
    with pytest.raises(AssertionError, match="other"):
        f.start(ctx(tmp_path, task_id="other"), CONF, tmp_path / "l")


def test_worker_fake_records_starts_and_stops(tmp_path):
    f = FakeWorkerAdapter({"backend": [ok()]})
    h = f.start(ctx(tmp_path), CONF, tmp_path / "l")
    f.stop(h)
    assert [c.task_id for c in f.started] == ["backend"] and f.stopped == [h]


def test_worker_fake_script_is_copied_so_two_fakes_do_not_share_state(tmp_path):
    script = {"backend": [ok()]}
    a, b = FakeWorkerAdapter(script), FakeWorkerAdapter(script)
    a.start(ctx(tmp_path), CONF, tmp_path / "l")
    b.start(ctx(tmp_path), CONF, tmp_path / "l")  # would raise if a had consumed the shared list


# ---- FakeTracker ----

def src(ref, title="t"):
    return Source("github", ref, title, "body", ["factory"], "alice", [])


def test_tracker_fake_satisfies_the_protocol():
    assert_satisfies(FakeTracker(), TrackerAdapter)


def test_tracker_list_new_uses_the_cursor():
    t = FakeTracker([src("a#1"), src("a#2")])
    assert [s.ref for s in t.list_new(None)] == ["a#1", "a#2"]
    cur = t.cursor()
    assert t.list_new(cur) == []
    t.add(src("a#3"))
    assert [s.ref for s in t.list_new(cur)] == ["a#3"]


def test_tracker_fetch_and_missing_item():
    t = FakeTracker([src("a#1", "first")])
    assert t.fetch("a#1").title == "first"
    with pytest.raises(KeyError):
        t.fetch("a#9")


def test_tracker_records_status_and_labels():
    t = FakeTracker([src("a#1")])
    t.ensure_labels(["factory:queued", "factory:done"])
    t.set_status("a#1", "factory:queued", comment="queued")
    t.set_status("a#1", "factory:running", link="http://x")
    assert t.labels == {"factory:queued", "factory:done"}
    assert t.last_status("a#1") == "factory:running" and t.last_status("zzz") is None
    assert t.statuses[0].comment == "queued" and t.statuses[1].link == "http://x"


def test_tracker_can_fail_once_then_recover():
    t = FakeTracker([src("a#1")])
    t.fail_next = ConnectionError("network down")
    with pytest.raises(ConnectionError):
        t.list_new(None)
    assert len(t.list_new(None)) == 1


# ---- FakePullRequests ----

def make_pr(prs, tmp_path):
    body = tmp_path / "body.md"
    body.write_text("summary")
    return prs.create(tmp_path, base="main", head="run-1", title="Fix login", body_file=body, labels=["factory"])


def test_prs_fake_satisfies_the_protocol(tmp_path):
    assert_satisfies(FakePullRequests(), PullRequests)


def test_prs_create_numbers_and_state(tmp_path):
    prs = FakePullRequests()
    pr = make_pr(prs, tmp_path)
    assert (pr.number, pr.head, pr.base) == (1, "run-1", "main")
    st = prs.state(pr)
    assert (st.state, st.ci) == ("open", "pending")
    assert prs.prs[1].body == "summary" and prs.prs[1].labels == ["factory"]


def test_prs_ci_red_then_green_and_human_merge(tmp_path):
    prs = FakePullRequests()
    pr = make_pr(prs, tmp_path)
    prs.set_ci(pr, "red", "2 tests failed")
    assert (prs.state(pr).ci, prs.state(pr).checks_output) == ("red", "2 tests failed")
    prs.set_ci(pr, "green")
    prs.human_merge(pr)
    assert prs.state(pr).state == "merged"


def test_prs_auto_merge_waits_for_green_ci(tmp_path):
    prs = FakePullRequests()
    pr = make_pr(prs, tmp_path)
    prs.merge(pr, auto=True)
    assert prs.state(pr).state == "open"
    prs.set_ci(pr, "green")
    assert prs.state(pr).state == "merged"


def test_prs_direct_merge_needs_green_and_an_open_pr(tmp_path):
    prs = FakePullRequests()
    pr = make_pr(prs, tmp_path)
    with pytest.raises(RuntimeError, match="CI pending"):
        prs.merge(pr, auto=False)
    prs.set_ci(pr, "green")
    prs.merge(pr, method="squash", auto=False)
    with pytest.raises(RuntimeError, match="merged"):
        prs.merge(pr)


def test_prs_closed_pr_and_reviewers_and_failure(tmp_path):
    prs = FakePullRequests()
    pr = make_pr(prs, tmp_path)
    prs.request_reviewers(pr, ["bob"])
    assert prs.prs[1].reviewers == ["bob"]
    prs.close(pr)
    assert prs.state(pr).state == "closed"
    prs.fail_next = ConnectionError("gh down")
    with pytest.raises(ConnectionError):
        prs.state(pr)
    assert prs.state(pr).state == "closed"
    with pytest.raises(KeyError):
        prs.state(PrRef(99, "u", "h", "b"))
