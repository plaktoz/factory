"""Module 6B acceptance criteria, run against FakeWorkerAdapter, FakeTracker, FakePullRequests and FakeClock."""

import json

import pytest

from factory_engine import state
from factory_engine.adapters.worker.fake import ok

TRIAGE_CHORE = json.dumps({"schema_version": 1, "type": "chore", "workflow": "chore", "confidence": 1.0,
                           "type_source": "explicit"})


def test_a_run_starts_with_triage_then_appends_the_chosen_workflows_stages(new_run, engine, tmp_path):
    run_dir = new_run()
    artifact = run_dir / "tasks" / "rules" / "work" / "triage.json"
    eng, _worker = engine({"rules": [ok(artifact)]}, writes={"rules": {"triage.json": TRIAGE_CHORE}})
    eng.tick("bump-q1w2e")
    run = state.read_run(run_dir)
    assert run.stages[0].id == "triage"
    assert run.workflow == "chore"


# ---- criterion 4: a usage record exists before the worker starts -------------------------------------------------

def test_every_attempt_has_a_usage_record_written_before_the_worker_starts(new_run, engine):
    from factory_engine import usage
    run_dir = new_run()
    artifact = run_dir / "tasks" / "rules" / "work" / "triage.json"
    eng, worker = engine({"rules": [ok(artifact)]}, writes={"rules": {"triage.json": TRIAGE_CHORE}})
    seen: list[str] = []
    real_start = worker.start

    def spy(ctx, conf, log):
        seen.append(usage.read_usage(run_dir, ctx.task_id)[-1].exit)  # what the usage file says at start time
        return real_start(ctx, conf, log)

    worker.start = spy
    eng.tick("bump-q1w2e")
    assert seen == ["started"]


# ---- a whole run, a failed gate, and a human stop ----------------------------------------------------------------

from engine_helpers import chore_script  # noqa: E402


def test_a_clean_chore_run_waits_at_its_merge_review_and_is_done_once_the_pull_request_merges(new_run, engine, prs):
    run_dir = new_run()
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    result = eng.run(["bump-q1w2e"])
    run = state.read_run(run_dir)
    assert result.runs == {"bump-q1w2e": "awaiting_approval"} and result.exit_code == 3
    assert [s.status for s in run.stages] == ["done", "done", "done"]
    assert run.pr is not None and len(prs.prs) == 1
    prs.human_merge(run.pr)
    assert eng.run(["bump-q1w2e"]).runs == {"bump-q1w2e": "done"}


def test_a_failed_gate_routes_back_with_a_feedback_record_and_blocks_at_the_loop_maximum(new_run, engine):
    from factory_engine.adapters.worker.fake import ok
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    # `change` writes outside its scope ("**" allows everything), so use the `implement` stage's lint gate instead:
    # a stub toolchain is not available, so force the failure with a scope-diff violation through a deny path.
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * 4)
    writes["change"] = {"change.json": "{}", ".github/workflows/x.yml": "bad"}  # .github/** is in policy.deny_paths
    eng, worker = engine(script, writes)
    # The fake writes into the task folder, not the worktree, so plant the violation in the task worktree directly.
    real_start = worker.start

    def start(ctx, conf, log):
        if ctx.task_id == "change":
            bad = ctx.worktree / ".github" / "workflows"
            bad.mkdir(parents=True, exist_ok=True)
            (bad / "x.yml").write_text("bad")
        return real_start(ctx, conf, log)

    worker.start = start
    result = eng.run(["bump-q1w2e"])
    run = state.read_run(run_dir)
    assert result.runs["bump-q1w2e"] == "blocked" and result.exit_code == 4
    assert run.loops == {"implement->implement": 2}
    assert run.attention is not None and run.attention.kind == "blocked"
    assert list((run_dir / "tasks" / "change" / "feedback").glob("*.json"))
    assert [e.type for e in state.read_events(run_dir) if e.type == "routed_back"]


def test_at_a_human_stop_the_engine_releases_the_lock_and_exits(new_run, engine, tmp_path):
    from factory_engine.lock import lock_status
    run_dir = new_run()
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    # Make the `implement` stage need approval, as bug-fix's `propose` stage does.
    wf_dir = eng.repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "chore.yaml").write_text((eng.repo / "factory" / "workflows" / "chore.yaml").read_text().replace(
        "    gate: [{check: scope-diff}, {check: lint-clean}]\n", "    gate: [{check: scope-diff}]\n    approval: human\n", 1))
    result = eng.run(["bump-q1w2e"])
    assert result.runs["bump-q1w2e"] == "awaiting_approval" and result.exit_code == 3
    assert lock_status(run_dir) != "live"          # the engine let go of the run
    assert state.read_run(run_dir).attention is not None


# ---- criterion 3: a timeout is recorded and the task retries from its last checkpoint ----------------------------

def test_a_task_over_its_timeout_is_recorded_and_a_worker_error_starts_a_new_attempt(new_run, engine):
    from factory_engine import usage
    from factory_engine.adapters.worker.fake import failed, ok, timeout
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[timeout(), failed("crash"), ok(work("change", "change.json"))])
    eng, _ = engine(script, writes)
    result = eng.run(["bump-q1w2e"])
    records = usage.read_usage(run_dir, "change")
    assert result.runs["bump-q1w2e"] == "awaiting_approval"
    assert [r.exit for r in records] == ["failed", "failed", "ok"]   # timeout and crash are worker errors, then success
    assert [r.attempt for r in records] == [1, 2, 3]


def test_a_task_that_runs_out_of_retries_blocks_the_run(new_run, engine):
    from factory_engine.adapters.worker.fake import failed
    run_dir = new_run()
    script, writes = chore_script(run_dir, change=[failed("crash")] * 3)
    eng, _ = engine(script, writes)
    result = eng.run(["bump-q1w2e"])
    assert result.runs["bump-q1w2e"] == "blocked" and result.exit_code == 4
    assert state.read_task(run_dir, "change").status == "failed"


# ---- criterion 5: a queued note restarts the worker at the next checkpoint ---------------------------------------

def _pause_before(eng, task_id: str) -> None:
    """Run the engine up to the point where `task_id` is the one running, using a blocking worker. Returns nothing."""


def test_a_queued_note_restarts_the_worker_and_is_marked_delivered(new_run, repo, cfg, tracker, prs, clock):
    import threading
    from blocking_worker import BlockingWorker
    from factory_engine import notes, usage
    from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
    from factory_engine.engine import Engine

    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json")), ok(work("change", "change.json"))])
    inner = FakeWorkerAdapter(script, writes=writes)
    worker = BlockingWorker(inner)
    eng = Engine(repo, cfg, workers={"fake": worker}, command=worker, tracker=tracker, prs=prs, clock=clock)
    # triage and the first worker start and block; the test queues a note while `change` is running, then releases it
    worker.release("rules")
    t = threading.Thread(target=lambda: eng.run(["bump-q1w2e"]), daemon=True)
    t.start()
    for _ in range(400):
        if "change" in worker.running:
            break
        threading.Event().wait(0.05)
    assert "change" in worker.running
    notes.queue_note(run_dir, "change", "Keep the public signature", by="you")
    for _ in range(400):  # the engine sees the note, stops the worker, and starts attempt 2
        if len(inner.started) and sum(1 for c in inner.started if c.task_id == "change") >= 2:
            break
        threading.Event().wait(0.05)
    worker.release("change")
    t.join(30)
    attempts = [r for r in usage.read_usage(run_dir, "change")]
    assert [r.exit for r in attempts][:1] == ["interrupted"]
    assert not notes.pending_notes(run_dir, "change")
    assert notes.delivered_notes(run_dir, "change") == ["Keep the public signature"]
    assert any(e.type == "worker_restarted" for e in state.read_events(run_dir))
    assert state.read_task(run_dir, "change").restarts == 1


# ---- criterion 2: tasks with no `needs` start together, up to `concurrency`; helpers reserve slots --------------------

FAN_OUT = """name: fan
type: chore
sink: pull_request
policy: {write: true, deny_paths: []}
defaults: {retries: 2, timeout_minutes: 30, checkpoint_every_minutes: 10, max_restarts: 3}
stages:
  - id: work
    tasks:
%s
"""


def _fan_workflow(eng, tasks: str) -> None:
    wf = eng.repo / ".factory" / "config" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "chore.yaml").write_text((FAN_OUT % tasks).replace("name: fan", "name: chore"))


def _run_blocking(new_run, repo, cfg, tracker, prs, clock, tasks: str, names: list[str], concurrency: int):
    import threading
    from blocking_worker import BlockingWorker
    from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
    from factory_engine.engine import Engine

    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))], **{n: [ok(work(n, f"{n}.json"))] for n in names}}
    writes = {"rules": {"triage.json": TRIAGE_CHORE}, **{n: {f"{n}.json": "{}"} for n in names}}
    inner = FakeWorkerAdapter(script, writes=writes)
    worker = BlockingWorker(inner)
    cfg.repo["concurrency"] = concurrency
    eng = Engine(repo, cfg, workers={"fake": worker}, command=worker, tracker=tracker, prs=prs, clock=clock)
    _fan_workflow(eng, tasks)
    worker.release("rules")
    t = threading.Thread(target=lambda: eng.run(["bump-q1w2e"]), daemon=True)
    t.start()
    return run_dir, worker, t


def _wait_until(cond, seconds=20):
    import time
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _settle(worker, quiet_for=1.0):
    """Wait until no worker has started for `quiet_for` seconds. A limit is shown by a start that does not happen, so the
    test must give the engine the chance to make it."""
    import time
    last, since = len(worker.inner.started), time.time()
    while time.time() - since < quiet_for:
        time.sleep(0.05)
        now = len(worker.inner.started)
        if now != last:
            last, since = now, time.time()


def test_tasks_with_no_needs_start_together_up_to_the_concurrency_limit(new_run, repo, cfg, tracker, prs, clock):
    tasks = "\n".join(f"      - {{id: t{i}, cmd: [/usr/bin/true], out: t{i}.json}}" for i in range(1, 5))
    run_dir, worker, t = _run_blocking(new_run, repo, cfg, tracker, prs, clock, tasks, ["t1", "t2", "t3", "t4"], 2)
    assert _wait_until(lambda: len(worker.running) == 2)
    _settle(worker)                              # give the engine time to start more, if it were allowed to
    assert worker.peak == 2 and sorted(worker.running) == ["t1", "t2"]   # four are ready; only two start at once
    for n in ("t1", "t2", "t3", "t4"):
        worker.release(n)
    t.join(60)
    assert worker.peak == 2 and not t.is_alive()


def test_a_task_starts_when_its_needs_are_done_while_a_slower_task_is_still_running(new_run, repo, cfg, tracker, prs, clock):
    tasks = ("      - {id: a, cmd: [/usr/bin/true], out: a.json}\n"
             "      - {id: b, cmd: [/usr/bin/true], out: b.json}\n"
             "      - {id: c, cmd: [/usr/bin/true], needs: [b], out: c.json}")
    run_dir, worker, t = _run_blocking(new_run, repo, cfg, tracker, prs, clock, tasks, ["a", "b", "c"], 3)
    assert _wait_until(lambda: sorted(worker.running) == ["a", "b"])
    worker.release("b")
    assert _wait_until(lambda: "c" in worker.running)     # `a` still runs, and `c` already started
    assert "a" in worker.running
    for n in ("a", "c"):
        worker.release(n)
    t.join(60)
    assert not t.is_alive()


def test_a_task_whose_when_does_not_hold_is_skipped_and_the_stage_still_finishes(new_run, repo, cfg, tracker, prs, clock):
    tasks = ("      - {id: a, cmd: [/usr/bin/true], when: {confidence_below: 0.5}, out: a.json}\n"
             "      - {id: b, cmd: [/usr/bin/true], out: b.json}\n"
             "      - {id: d, cmd: [/usr/bin/true], needs: [a], out: d.json}")
    run_dir, worker, t = _run_blocking(new_run, repo, cfg, tracker, prs, clock, tasks, ["b", "d"], 2)
    assert _wait_until(lambda: {"b", "d"} <= set(worker.running))   # triage says confidence 1.0, so `a` is skipped
    for n in ("b", "d"):
        worker.release(n)
    t.join(60)
    assert not t.is_alive()
    assert sorted(c.task_id for c in worker.inner.started if c.task_id in ("a", "b", "d")) == ["b", "d"]
    assert state.read_task(run_dir, "a").status == "done"
    assert state.read_task(run_dir, "d").task_base == "bump-q1w2e"      # `a` made no branch, so `d` starts from the run
    assert "stage_done" in [e.type for e in state.read_events(run_dir) if e.data.get("stage") == "work"]


def test_a_task_after_a_skipped_task_starts_from_the_skipped_tasks_own_dependency(new_run, repo, cfg, tracker, prs, clock):
    tasks = ("      - {id: r, cmd: [/usr/bin/true], out: r.json}\n"
             "      - {id: a, cmd: [/usr/bin/true], needs: [r], when: {confidence_below: 0.5}, out: a.json}\n"
             "      - {id: d, cmd: [/usr/bin/true], needs: [a], out: d.json}")
    run_dir, worker, t = _run_blocking(new_run, repo, cfg, tracker, prs, clock, tasks, ["r", "d"], 2)
    assert _wait_until(lambda: "r" in worker.running)
    worker.release("r")
    assert _wait_until(lambda: "d" in worker.running)             # `a` is skipped once `r` is done; `d` follows it
    worker.release("d")
    t.join(60)
    assert not t.is_alive()
    assert state.read_task(run_dir, "d").task_base == "bump-q1w2e--r"
    assert "stage_done" in [e.type for e in state.read_events(run_dir) if e.data.get("stage") == "work"]


READ_ONLY_CHORE = """name: chore
type: chore
sink: doc
policy: {write: false, deny_paths: []}
defaults: {retries: 2, timeout_minutes: 30, checkpoint_every_minutes: 10, max_restarts: 3}
stages:
  - id: one
    tasks:
      - {id: a, cmd: [/usr/bin/true], out: a.json}
  - id: two
    tasks:
      - {id: b, cmd: [/usr/bin/true], out: report.md}
"""


def test_a_read_only_run_starts_its_tasks_from_the_run_commit_in_two_stages(new_run, repo, cfg, tracker, prs, clock):
    import threading
    from blocking_worker import BlockingWorker
    from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
    from factory_engine.engine import Engine
    from gitutil import run as git

    # The kit is read from main's commit when a run starts (module 3), so the workflow is committed before new_run.
    wf = repo / ".factory" / "config" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "chore.yaml").write_text(READ_ONLY_CHORE)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "read-only chore workflow")
    git(repo, "push", "-q", "origin", "main")

    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))], "a": [ok(work("a", "a.json"))], "b": [ok(work("b", "report.md"))]}
    writes = {"rules": {"triage.json": TRIAGE_CHORE}, "a": {"a.json": "{}"}, "b": {"report.md": "# report\n"}}
    worker = BlockingWorker(FakeWorkerAdapter(script, writes=writes))
    eng = Engine(repo, cfg, workers={"fake": worker}, command=worker, tracker=tracker, prs=prs, clock=clock)
    worker.release("rules")
    t = threading.Thread(target=lambda: eng.run(["bump-q1w2e"]), daemon=True)
    t.start()
    assert _wait_until(lambda: "a" in worker.running)
    worker.release("a")
    assert _wait_until(lambda: "b" in worker.running)
    worker.release("b")
    t.join(60)
    assert not t.is_alive()
    # Stage `one` joined `a` onto the run commit, so `b` (stage two) starts from the commit after that join, not `bump-q1w2e`.
    base_of_b = state.read_task(run_dir, "b").task_base
    assert base_of_b is not None and len(base_of_b) == 40          # a commit: no branch named after the run exists
    assert base_of_b in git(state.read_run(run_dir).worktree, "rev-list", "HEAD")
    assert [e.data.get("stage") for e in state.read_events(run_dir) if e.type == "stage_done"] == ["triage", "one", "two"]
    # The doc sink commits the report to a new branch and opens its pull request (module 13), so the run waits at merge review.
    run = state.read_run(run_dir)
    assert run.status == "awaiting_approval" and run.pr is not None and run.pr.head == "bump-q1w2e"
    assert "pr_opened" in [e.type for e in state.read_events(run_dir)]


def test_a_task_with_a_helper_maximum_of_two_reserves_three_slots(new_run, repo, cfg, tracker, prs, clock):
    tasks = ("      - {id: big, skill: fix, helpers: {mode: auto, max: 2}, out: big.json}\n"
             "      - {id: small, cmd: [/usr/bin/true], out: small.json}")
    run_dir, worker, t = _run_blocking(new_run, repo, cfg, tracker, prs, clock, tasks, ["big", "small"], 3)
    assert _wait_until(lambda: len(worker.running) >= 1)
    _settle(worker)
    assert worker.running == ["big"]             # 3 slots: `big` takes all of them, so `small` waits
    for n in ("big", "small"):
        worker.release(n)
    t.join(60)
    assert worker.peak == 1 and not t.is_alive()


# ---- criterion 9: after each join, conflict signals are written to run.json --------------------------------------

def test_after_each_join_conflict_signals_are_written_to_run_json(new_run, repo, cfg, tracker, prs, clock):
    import threading
    from blocking_worker import BlockingWorker
    from gitutil import run as git
    from factory_engine.adapters.worker.fake import FakeWorkerAdapter
    from factory_engine.engine import Engine

    run_dir = new_run()
    script, writes = chore_script(run_dir)
    inner = FakeWorkerAdapter(script, writes=writes)
    worker = BlockingWorker(inner)
    eng = Engine(repo, cfg, workers={"fake": worker}, command=worker, tracker=tracker, prs=prs, clock=clock)
    worker.release("rules")
    t = threading.Thread(target=lambda: eng.run(["bump-q1w2e"]), daemon=True)
    t.start()
    assert _wait_until(lambda: "change" in worker.running)        # the run branch exists now
    git(repo, "checkout", "-q", "main")                            # the base moves on while `change` works
    (repo / "services" / "other.py").write_text("y = 2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "someone else merged")
    git(repo, "push", "-q", "origin", "main")                      # conflict_signals reads origin/main
    git(repo, "fetch", "-q", "origin")
    worker.release("change")
    worker.release("check")
    t.join(60)
    run = state.read_run(run_dir)
    assert run.signals is not None and run.signals.behind_base == 1


# ---- criterion 8: kill the engine mid-task, then resume ------------------------------------------------------------

CHILD = """
import sys, time, json
from pathlib import Path
sys.path.insert(0, {engine_dir!r})
sys.path.insert(0, {tests_dir!r})
from factory_engine import skills
from factory_engine.adapters.tracker.fake import FakeTracker
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
from factory_engine.clock import FakeClock
from factory_engine.config import Config
from factory_engine.engine import Engine
from factory_engine.fake_prs import FakePullRequests
skills.use_kit(Path({kit!r}))
run_dir = Path({run_dir!r})
work = lambda t, n: run_dir / "tasks" / t / "work" / n
class Hang(FakeWorkerAdapter):
    def wait(self, handle, timeout_s):
        # the worker has written half an edit into its worktree, then the engine is killed before it finishes
        (Path(handle.data["ctx"].worktree) / "services" / "half.py").write_text("half = 1")
        print("RUNNING", flush=True)
        time.sleep(600)
class Spy(Hang):
    def start(self, ctx, conf, log):
        h = super().start(ctx, conf, log); h.data["ctx"] = ctx; return h
script = {{"rules": [ok(work("rules", "triage.json"))], "change": [ok(work("change", "change.json"))]}}
writes = {{"rules": {{"triage.json": {triage!r}}}, "change": {{"change.json": "{{}}"}}}}
class Mixed(Spy):
    def wait(self, handle, timeout_s):
        if handle.task_id == "change":
            return Hang.wait(self, handle, timeout_s)
        return handle.data["result"]
cfg = Config(machine={cfg_machine!r}, repo={{"base_branch": "main"}})
w = Mixed(script, writes=writes)
eng = Engine(Path({repo!r}), cfg, workers={{"fake": w}}, command=w, tracker=FakeTracker(),
             prs=FakePullRequests(), clock=FakeClock())
eng.run(["bump-q1w2e"])
"""


def test_kill_the_engine_mid_task_then_resume(new_run, engine, repo, cfg, tmp_path, monkeypatch):
    import subprocess
    import sys
    from pathlib import Path
    from factory_engine import usage
    from factory_engine.lock import lock_status

    run_dir = new_run()
    code = CHILD.format(engine_dir=str(Path(__file__).resolve().parents[2]), tests_dir=str(Path(__file__).resolve().parent),
                        kit=str(Path(__file__).resolve().parents[3]), run_dir=str(run_dir), repo=str(repo),
                        triage=TRIAGE_CHORE, cfg_machine=cfg.machine)
    env = {**__import__("os").environ, "FACTORY_HOME": str(state.factory_home())}
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, env=env)
    assert child.stdout.readline().strip() == "RUNNING"
    assert lock_status(run_dir) == "live"
    child.kill()
    child.wait()
    assert usage.read_usage(run_dir, "change")[-1].exit == "started"      # the attempt was cut off
    # resume: only unfinished tasks run, from a clean worktree
    script, writes = chore_script(run_dir)
    script["rules"] = []                                                   # triage is done: it must not run again
    eng, worker = engine(script, writes)
    eng.resume("bump-q1w2e")
    status = state.read_run(run_dir).status
    ran = [c.task_id for c in worker.started]
    records = usage.read_usage(run_dir, "change")
    assert status == "awaiting_approval"  # the pull request is open; the run waits at its merge review
    assert "rules" not in ran and ran.count("change") == 1
    assert [r.exit for r in records] == ["interrupted", "ok"]
    patches = list((run_dir / "tasks" / "change").glob("discarded-*.patch"))
    assert patches and "half.py" in patches[0].read_text()          # the cut-off edit was saved, then discarded
    assert not (state.read_task(run_dir, "change").worktree / "services" / "half.py").exists()   # back at the checkpoint


# ---- criterion 5, the cap: restarts stop at max_restarts, and the note stays queued --------------------------------

def test_restarts_stop_at_max_restarts_and_the_note_stays_queued(new_run, repo, cfg, tracker, prs, clock):
    import threading
    from blocking_worker import BlockingWorker
    from factory_engine import notes, usage
    from factory_engine.adapters.worker.fake import FakeWorkerAdapter, ok
    from factory_engine.engine import Engine

    cfg.repo["max_restarts"] = 1
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json")), ok(work("change", "change.json"))])
    inner = FakeWorkerAdapter(script, writes=writes)
    worker = BlockingWorker(inner)
    eng = Engine(repo, cfg, workers={"fake": worker}, command=worker, tracker=tracker, prs=prs, clock=clock)
    worker.release("rules")
    worker.release("check")
    t = threading.Thread(target=lambda: eng.run(["bump-q1w2e"]), daemon=True)
    t.start()
    starts = lambda: sum(1 for c in inner.started if c.task_id == "change")  # noqa: E731
    assert _wait_until(lambda: "change" in worker.running)
    notes.queue_note(run_dir, "change", "first", by="you")
    assert _wait_until(lambda: starts() == 2 and "change" in worker.running)       # restart 1 of 1
    notes.queue_note(run_dir, "change", "second", by="you")
    _settle(worker)                                                                 # the engine had its chance
    assert starts() == 2                                                            # no third attempt: the cap holds
    worker.release("change")
    t.join(60)
    assert state.read_task(run_dir, "change").restarts == 1
    assert [n.text for n in notes.pending_notes(run_dir, "change")] == ["second"]  # the note stays queued
    assert [r.exit for r in usage.read_usage(run_dir, "change")] == ["interrupted", "ok"]


def test_the_engine_gives_each_worker_its_tasks_own_timeout(new_run, engine):
    from factory_engine.adapters.worker.fake import ok
    run_dir = new_run()
    wf_dir = engine({}, {})[0].repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    chore = (wf_dir.parents[2] / "factory" / "workflows" / "chore.yaml").read_text()
    (wf_dir / "chore.yaml").write_text(chore.replace("{id: change, skill: implement,", "{id: change, skill: implement, timeout_minutes: 7,", 1))
    script, writes = chore_script(run_dir)
    eng, worker = engine(script, writes)
    seen: dict[str, int] = {}
    real_wait = worker.wait
    worker.wait = lambda handle, timeout_s: (seen.__setitem__(handle.task_id, timeout_s), real_wait(handle, timeout_s))[1]
    eng.run(["bump-q1w2e"])
    assert seen["change"] == 7 * 60            # the task's own timeout, in seconds
    assert seen["check"] == 30 * 60            # the workflow default


# ---- triage stop: the options are the workflows that load (module 4) ----------------------------------------------

UNRESOLVED = json.dumps({"schema_version": 1, "type": None, "workflow": None, "confidence": 0.0, "type_source": "keyword"})


def _triage_that_cannot_decide(new_run, engine):
    run_dir = new_run()
    artifact = run_dir / "tasks" / "rules" / "work" / "triage.json"
    eng, _ = engine({"rules": [ok(artifact)], "classify": [ok(artifact)]},
                    writes={"rules": {"triage.json": UNRESOLVED}, "classify": {"triage.json": UNRESOLVED}})
    return run_dir, eng


def test_a_triage_stop_offers_only_workflows_that_load(new_run, engine):
    run_dir, eng = _triage_that_cannot_decide(new_run, engine)
    # the shipped kit has bug-fix and chore only; feature, new-app and research do not load in phase 1a
    result = eng.run(["bump-q1w2e"])
    run = state.read_run(run_dir)
    assert result.runs["bump-q1w2e"] == "awaiting_approval" and result.exit_code == 3
    from factory_engine import decisions as D
    options = [o["id"] for o in D.read_decision(run_dir, "triage", 1)["packet"]["decisions"][0]["options"]]
    assert sorted(options) == ["bug-fix", "chore"]
    assert run.attention is not None and run.attention.kind == "triage"


def test_a_triage_stop_with_fewer_than_two_loading_workflows_blocks_with_the_reason(new_run, engine, monkeypatch):
    run_dir, eng = _triage_that_cannot_decide(new_run, engine)
    monkeypatch.setattr(eng, "_loads", lambda wid: wid == "chore")
    result = eng.run(["bump-q1w2e"])
    run = state.read_run(run_dir)
    assert result.runs["bump-q1w2e"] == "blocked" and result.exit_code == 4
    assert run.attention is not None and run.attention.kind == "blocked"
    assert "only 1 loads (chore)" in run.attention.summary
    assert [e.type for e in state.read_events(run_dir) if e.type == "run_blocked"]


# ---- module 8 step 3: a failed gate undoes that stage's join, and nothing before it ------------------------------

def _plant_in_task_worktree(worker, task_id: str, rel: str, text: str) -> None:
    real_start = worker.start

    def start(ctx, conf, log):
        if ctx.task_id == task_id:
            target = ctx.worktree / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        return real_start(ctx, conf, log)

    worker.start = start


def test_a_failed_gate_resets_the_run_branch_to_its_pre_join_commit(new_run, engine, repo):
    """`change` plants a file under `.github/`, which `policy.deny_paths` forbids, so `implement`'s scope-diff gate
    fails after the join. The run branch must come back to the commit it had before that join."""
    from factory_engine import gitops
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * 4)
    eng, worker = engine(script, writes)
    _plant_in_task_worktree(worker, "change", ".github/workflows/x.yml", "bad")
    eng.run(["bump-q1w2e"])
    run = state.read_run(run_dir)
    base = gitops.git(repo, "rev-parse", "main").stdout.strip()
    assert gitops.git(run.worktree, "rev-parse", "HEAD").stdout.strip() == base   # every failed join was undone
    assert not (run.worktree / ".github" / "workflows" / "x.yml").exists()        # the bad file is not on the branch
    assert gitops.git(run.worktree, "status", "--porcelain").stdout.strip() == ""
    assert run.loops["implement->implement"] == 2          # the gate failed and routed back twice before blocking


# ---- module 6 lifecycle step 4: an answer restarts an engine, which continues where the run stopped -------------

def _approve_implement(eng):
    wf_dir = eng.repo / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "chore.yaml").write_text((eng.repo / "factory" / "workflows" / "chore.yaml").read_text().replace(
        "    gate: [{check: scope-diff}, {check: lint-clean}]\n", "    gate: [{check: scope-diff}]\n    approval: human\n", 1))


def _answer(run_dir, stage, choice_id):
    from factory_engine import decisions as D
    visit = 1
    doc = D.read_decision(run_dir, stage, visit)
    return D.record(run_dir, stage, visit, packet_sha=doc["packet"]["sha"],
                    choices={d["id"]: choice_id for d in doc["packet"]["decisions"]}, by="owner", channel="cli")


def test_an_answered_approval_stop_lets_a_new_engine_continue_the_run_to_done(new_run, engine):
    run_dir = new_run()
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    _approve_implement(eng)
    assert eng.run(["bump-q1w2e"]).runs["bump-q1w2e"] == "awaiting_approval"
    _answer(run_dir, "implement", "approve")
    result = eng.run(["bump-q1w2e"])                      # the driver starts a new engine once the answer is in
    assert result.runs["bump-q1w2e"] == "awaiting_approval" and result.exit_code == 3
    eng.prs.human_merge(state.read_run(run_dir).pr)
    assert eng.run(["bump-q1w2e"]).runs["bump-q1w2e"] == "done"


def test_an_unanswered_approval_stop_stays_parked_when_an_engine_starts(new_run, engine):
    run_dir = new_run()
    script, writes = chore_script(run_dir)
    eng, _ = engine(script, writes)
    _approve_implement(eng)
    eng.run(["bump-q1w2e"])
    assert eng.run(["bump-q1w2e"]).runs["bump-q1w2e"] == "awaiting_approval"   # no answer: nothing moves


def test_an_answered_triage_stop_continues_with_the_chosen_workflow(new_run, engine):
    run_dir = new_run()
    script, writes = chore_script(run_dir)
    artifact = run_dir / "tasks" / "rules" / "work" / "triage.json"
    script["classify"] = [ok(artifact)]
    writes["rules"] = {"triage.json": UNRESOLVED}            # the rules cannot decide, and neither can classify
    writes["classify"] = {"triage.json": UNRESOLVED}
    eng, _ = engine(script, writes)
    assert eng.run(["bump-q1w2e"]).runs["bump-q1w2e"] == "awaiting_approval"
    _answer(run_dir, "triage", "chore")
    result = eng.run(["bump-q1w2e"])
    run = state.read_run(run_dir)
    assert run.workflow == "chore" and run.request.type == "chore" and run.request.type_source == "explicit"
    assert result.runs["bump-q1w2e"] == "awaiting_approval"
    assert [e.type for e in state.read_events(run_dir) if e.type == "triage_answered"]


# ---- D7 (owner decision 2026-11-22): one exit code for several runs, blocked over waiting over failed over success ----

@pytest.mark.parametrize("statuses,code", [
    (["done", "done"], 0),
    (["done", "failed"], 1),
    (["failed", "awaiting_approval"], 3),            # a failure hides behind a run waiting on a person
    (["failed", "awaiting_approval", "blocked"], 4),
    (["done", "blocked", "failed"], 4),
])
def test_the_exit_code_for_several_runs_is_blocked_then_waiting_then_failed_then_success(engine, new_run, monkeypatch, statuses, code):
    new_run()
    eng, _ = engine({})
    ids = [f"r{i}" for i in range(len(statuses))]
    by_id = dict(zip(ids, statuses))
    monkeypatch.setattr(eng, "_drive", lambda rid: by_id[rid])
    result = eng.run(ids)
    assert result.runs == by_id and result.exit_code == code
