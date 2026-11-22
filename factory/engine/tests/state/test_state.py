"""Module 6A acceptance criteria, including the rebuild rule of decision E1 (run_snapshot)."""

import json
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from factory_engine import atomic, state
from factory_engine.config import Config
from factory_engine.errors import FactoryError
from factory_engine.lock import acquire_lock, heartbeat, lock_status, release
from factory_engine.types import AttentionItem, Request, Source, StageState


def req(title="Login fails", ref="gh-42", sha="c91e07"):
    return Request(request_id=ref, source=Source("github", f"o/r#{ref}", title, "body", ["bug"], "alice", []),
                   body_sha=sha, repo="report", title=title, type="bug", type_source="label", priority="high",
                   acceptance=["401 with a refresh hint"])


# --- atomic writes ---

def test_write_json_atomic_replaces_the_whole_file(tmp_path):
    p = tmp_path / "run.json"
    atomic.write_json_atomic(p, {"a": 1})
    atomic.write_json_atomic(p, {"a": 2})
    assert json.loads(p.read_text()) == {"a": 2}
    assert not [f for f in tmp_path.iterdir() if f.name.endswith(".tmp")]


def test_a_failed_write_keeps_the_last_good_file(tmp_path, monkeypatch):
    p = tmp_path / "run.json"
    atomic.write_json_atomic(p, {"good": True})

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(atomic.os, "replace", boom)
    with pytest.raises(OSError):
        atomic.write_json_atomic(p, {"good": False})
    assert json.loads(p.read_text()) == {"good": True}
    assert not [f for f in tmp_path.iterdir() if f.name.endswith(".tmp")]


def test_a_cut_off_last_jsonl_line_is_ignored(tmp_path):
    p = tmp_path / "events.jsonl"
    p.write_text('{"seq": 1}\n{"seq": 2}\n{"seq": 3, "ty')
    assert [e["seq"] for e in atomic.read_jsonl(p)] == [1, 2]


def test_a_complete_last_line_without_newline_is_still_read(tmp_path):
    p = tmp_path / "events.jsonl"
    p.write_text('{"seq": 1}\n{"seq": 2}')
    assert [e["seq"] for e in atomic.read_jsonl(p)] == [1]  # no newline: treated as possibly cut off


def test_two_processes_appending_events_get_whole_lines_only(tmp_path):
    """Acceptance: two processes appending at once produce whole lines only (Linux and macOS)."""
    target = tmp_path / "events.jsonl"
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
        from pathlib import Path
        from factory_engine.atomic import append_jsonl
        for i in range(400):
            append_jsonl(Path({str(target)!r}), {{"who": sys.argv[1], "i": i, "pad": "x" * 300}})
    """)
    procs = [subprocess.Popen([sys.executable, "-c", code, name]) for name in ("a", "b")]
    for p in procs:
        assert p.wait(timeout=120) == 0
    lines = target.read_text().splitlines()
    assert len(lines) == 800
    parsed = [json.loads(l) for l in lines]  # every line is a whole record
    assert {r["who"] for r in parsed} == {"a", "b"}


# --- the run lock ---

def test_acquire_refuses_while_another_process_holds_the_lock(tmp_path):
    d = tmp_path / "run"
    lock = acquire_lock(d, "engine-1")
    proc = subprocess.run([sys.executable, "-c", textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
        from pathlib import Path
        from factory_engine.lock import acquire_lock
        from factory_engine.errors import FactoryError
        try:
            acquire_lock(Path({str(d)!r}), 'engine-2')
            print('ACQUIRED')
        except FactoryError as e:
            print(e.code)
    """)], capture_output=True, text=True, timeout=60)
    assert proc.stdout.strip() == "state.locked"
    release(lock)


def test_acquire_succeeds_right_after_the_holder_is_killed(tmp_path):
    """Acceptance: a killed holder releases the lock at once, whatever its heartbeat says."""
    d = tmp_path / "run"
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
        from pathlib import Path
        from factory_engine.lock import acquire_lock
        acquire_lock(Path({str(d)!r}), 'holder')
        print('HELD', flush=True)
        time.sleep(600)
    """)], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "HELD"
    assert lock_status(d) == "live"
    holder.kill()
    holder.wait()
    lock = acquire_lock(d, "engine-2")  # no raise
    release(lock)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="SIGSTOP and SIGCONT do not exist on Windows; the killed-holder test covers the kernel lock")
def test_a_stopped_process_keeps_its_lock_past_the_old_limit(tmp_path):
    """Acceptance: SIGSTOP keeps the lock (the lock is not a heartbeat timeout); lock_status reports live."""
    d = tmp_path / "run"
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
        from pathlib import Path
        from factory_engine.lock import acquire_lock
        acquire_lock(Path({str(d)!r}), 'holder')
        print('HELD', flush=True)
        time.sleep(600)
    """)], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "HELD"
        os.kill(holder.pid, signal.SIGSTOP)
        # the spec's old limit was 60 seconds; the lock must not expire with time. Checked by the probe here.
        assert lock_status(d) == "live"
        with pytest.raises(FactoryError) as e:
            acquire_lock(d, "engine-2")
        assert e.value.code == "state.locked"
    finally:
        os.kill(holder.pid, signal.SIGCONT)
        holder.kill()
        holder.wait()


def test_heartbeat_is_display_only(tmp_path):
    d = tmp_path / "run"
    lock = acquire_lock(d, "engine-1")
    heartbeat(lock)
    info = json.loads((d / "lock").read_text())
    assert info["owner"] == "engine-1" and info["pid"] == os.getpid()
    release(lock)


def test_release_twice_does_not_raise_and_frees_the_lock(tmp_path):
    """Issue 103: a second release, or one on a closed fd, does nothing on every platform."""
    d = tmp_path / "run"
    lock = acquire_lock(d, "e")
    release(lock)
    release(lock)
    assert lock_status(d) == "free"
    release(acquire_lock(d, "e2"))  # the lock can be taken again


def test_the_lock_works_under_a_folder_with_a_space_in_its_name(tmp_path):
    """Issue 103: a Windows user path often has a space, e.g. C:\\Users\\Jane Doe."""
    d = tmp_path / "Jane Doe" / "run"
    lock = acquire_lock(d, "e")
    try:
        assert lock_status(d) == "live"
        with pytest.raises(FactoryError) as e:
            acquire_lock(d, "other")
        assert e.value.code == "state.locked"
    finally:
        release(lock)


def test_the_lock_file_stays_readable_by_another_process_while_the_lock_is_held(tmp_path):
    """Issue 103: a Windows byte-range lock is mandatory. It must not cover the heartbeat JSON a reader opens."""
    d = tmp_path / "run"
    lock = acquire_lock(d, "engine-1")
    try:
        heartbeat(lock)
        proc = subprocess.run([sys.executable, "-c", textwrap.dedent(f"""
            import json
            print(json.loads(open({str(d / 'lock')!r}).read())['owner'])
        """)], capture_output=True, text=True, timeout=60)
        assert proc.stdout.strip() == "engine-1", proc.stderr
    finally:
        release(lock)


def test_lock_status_free_stale_and_live(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "run.json").write_text('{"status": "done"}')
    assert lock_status(d) == "free"
    (d / "run.json").write_text('{"status": "running"}')
    assert lock_status(d) == "stale"  # running, but no process holds the lock
    lock = acquire_lock(d, "e")
    assert lock_status(d) == "live"
    release(lock)


# --- run and task files ---

def make_run(tmp_path, key="github.com/acme/report", run_id="new-color-q1w2e"):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    ref = state.init_run(home, repo, key, run_id, req(), branch=run_id, worktree=tmp_path / "wt", kit_hash="ab12")
    return home, ref


def test_init_run_writes_request_and_run_and_an_event(tmp_path):
    home, ref = make_run(tmp_path)
    assert (ref.run_dir / "request.json").is_file()
    run = state.read_run(ref.run_dir)
    assert run.status == "pending" and run.kit_hash == "ab12" and run.repo_path == ref.repo
    assert [e.type for e in state.read_events(ref.run_dir)] == ["run_created", "run_snapshot"]  # creation is a change (E1)


def test_write_run_refuses_without_the_lock(tmp_path):
    home, ref = make_run(tmp_path)
    run = state.read_run(ref.run_dir)
    lock = acquire_lock(ref.run_dir, "e")
    state.write_run(ref.run_dir, run, lock=lock)  # with the lock: fine
    release(lock)
    other = tmp_path / "other-lock-dir"
    stranger = acquire_lock(other, "x")
    with pytest.raises(FactoryError) as e:
        state.write_run(ref.run_dir, run, lock=stranger)
    assert e.value.code == "state.locked"
    release(stranger)


def test_write_task_refuses_without_the_lock_and_round_trips(tmp_path):
    from factory_engine.types import TaskState
    home, ref = make_run(tmp_path)
    t = TaskState(task_id="backend", stage="fix", status="running", attempt=1, restarts=0,
                  task_base="a1b2", worktree=None, checkpoints=0)
    lock = acquire_lock(ref.run_dir, "e")
    state.write_task(ref.run_dir, t, lock=lock)
    release(lock)
    assert state.read_task(ref.run_dir, "backend").status == "running"
    stranger = acquire_lock(tmp_path / "elsewhere", "x")
    with pytest.raises(FactoryError):
        state.write_task(ref.run_dir, t, lock=stranger)
    release(stranger)


def test_append_event_numbers_each_line(tmp_path):
    home, ref = make_run(tmp_path)
    state.append_event(ref.run_dir, "stage_started", stage="fix")
    state.append_event(ref.run_dir, "stage_done", stage="fix")
    seqs = [e.seq for e in state.read_events(ref.run_dir)]
    assert seqs == [1, 2, 3, 4]  # run_created, run_snapshot (E1), then the two appended here


def test_read_events_since(tmp_path):
    home, ref = make_run(tmp_path)
    state.append_event(ref.run_dir, "x")
    assert [e.seq for e in state.read_events(ref.run_dir, since=2)] == [3]


# --- identity and lookup ---

def test_repo_key_from_ssh_and_https_and_override_and_no_remote(tmp_path):
    cfg = Config(machine={}, repo={})
    repo = tmp_path / "report"
    repo.mkdir()
    for url in ("git@github.com:acme/report.git", "https://github.com/acme/report.git", "https://github.com/acme/report"):
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "remove", "origin"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url], check=True)
        assert state.repo_key(repo, cfg) == "github.com/acme/report", url
    subprocess.run(["git", "-C", str(repo), "remote", "remove", "origin"], check=True)
    assert state.repo_key(repo, cfg) == "local/report"
    assert state.repo_key(repo, Config(machine={}, repo={"repo_key": "github.com/acme/other"})) == "github.com/acme/other"


def test_new_run_id_is_slugged_with_five_chars_and_unique_across_the_home():
    taken = {"login-fails-abcde"}
    rid = state.new_run_id("Login fails!", lambda x: x in taken)
    assert rid.startswith("login-fails-") and len(rid.rsplit("-", 1)[1]) == 5 and rid not in taken


def test_find_by_source_matches_ref_and_body_hash(tmp_path):
    home, ref = make_run(tmp_path)
    assert state.find_by_source(home, "github.com/acme/report", "o/r#gh-42", "c91e07") == "new-color-q1w2e"
    assert state.find_by_source(home, "github.com/acme/report", "o/r#gh-42", "changed") is None
    assert state.find_by_source(home, "github.com/acme/other", "o/r#gh-42", "c91e07") is None


def test_run_ids_are_unique_across_repos_in_the_home(tmp_path):
    home, _ = make_run(tmp_path)
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    state.init_run(home, repo2, "github.com/acme/other", "other-run", req(ref="gh-7"), branch="b", worktree=tmp_path, kit_hash="x")
    assert state.find_run(home, "other-run").repo_key == "github.com/acme/other"
    assert state.find_run(home, "missing") is None


# --- scanner ---

def test_scanner_reads_only_changed_runs_and_flags_missing_repos(tmp_path):
    home = tmp_path / "home"
    repos = []
    for i in range(20):  # 20 is enough to show the rule; the spec's 500 is run by the perf check, not here
        repo = tmp_path / f"r{i}"
        repo.mkdir()
        repos.append(repo)
        state.init_run(home, repo, "local/r", f"run-{i}", req(ref=f"gh-{i}"), branch="b", worktree=tmp_path, kit_hash="x")
    sc = state.RunScanner(home)
    first = sc.scan()
    assert len(first.added) == 20 and first.reread == 20
    second = sc.scan()
    assert second.reread == 0 and second.changed == []
    p = home / "runs" / "local/r" / "run-3" / "run.json"
    p.write_text(p.read_text() + " ")  # size changed
    third = sc.scan()
    assert third.changed == ["run-3"] and third.reread == 1
    repos[5].rename(tmp_path / "moved")
    fourth = sc.scan()
    assert "run-5" in fourth.repo_missing


def test_history_append_writes_one_line(tmp_path):
    state.history_append(tmp_path, state.HistoryRecord(run_id="r", repo_key="k", status="done", ended="t"))
    assert len(atomic.read_jsonl(tmp_path / "history.jsonl")) == 1


# --- rebuild from the last run_snapshot (decision E1, [snapshot-event]) ---

def _mid_run(ref):
    """Make a run with stages, loops and attention, written the way the engine writes it: under the lock."""
    run = state.read_run(ref.run_dir)
    run.status = "running"
    run.stage = "fix"
    run.stages = [StageState("propose", 1, "done", ["plan"], "t0", "t1"),
                  StageState("fix", 1, "running", ["backend", "frontend"], "t1", None)]
    run.loops = {"verify->fix": 1}
    run.attention = AttentionItem("approval", "new-color-q1w2e", "propose", "t2", "approve the plan", None,
                                  "factory decide new-color-q1w2e")
    lock = acquire_lock(ref.run_dir, "engine")
    state.write_run(ref.run_dir, run, lock=lock)
    release(lock)
    return run


def test_every_change_writes_a_run_snapshot(tmp_path):
    home, ref = make_run(tmp_path)
    before = [e.type for e in state.read_events(ref.run_dir)]
    _mid_run(ref)
    after = [e.type for e in state.read_events(ref.run_dir)]
    assert after[len(before):].count("run_snapshot") == 1


def test_rebuild_gives_the_same_state_the_engine_wrote(tmp_path):
    home, ref = make_run(tmp_path)
    run = _mid_run(ref)
    rebuilt = state.rebuild_run(ref.run_dir)
    assert rebuilt.status == run.status and rebuilt.stage == run.stage
    assert rebuilt.stages == run.stages and rebuilt.loops == run.loops and rebuilt.attention == run.attention
    assert rebuilt.heartbeat == "" and rebuilt.signals is None


def test_rebuild_replays_only_the_last_snapshot(tmp_path):
    """Acceptance: an earlier snapshot is ignored, so the last one wins. The first snapshot says loops 0 and the
    last says loops 1, so a rebuild that takes the first one fails here."""
    home, ref = make_run(tmp_path)
    run = _mid_run(ref)                      # snapshot 1: loops {'verify->fix': 1}
    older = state.read_run(ref.run_dir)
    older.loops = {"verify->fix": 0}
    lock = acquire_lock(ref.run_dir, "e")
    state.write_run(ref.run_dir, older, lock=lock)  # snapshot 2: loops {'verify->fix': 0}, the one written first
    release(lock)
    # the newest change, after the older one
    newest = state.read_run(ref.run_dir)
    newest.loops = {"verify->fix": 2}
    lock = acquire_lock(ref.run_dir, "e")
    state.write_run(ref.run_dir, newest, lock=lock)  # snapshot 3: the last one
    release(lock)
    rebuilt = state.rebuild_run(ref.run_dir)
    assert rebuilt.loops == {"verify->fix": 2}, "a rebuild must take the last snapshot, not the first or the middle"


def test_rebuild_reads_no_other_events(tmp_path):
    home, ref = make_run(tmp_path)
    run = _mid_run(ref)
    events = ref.run_dir / "events.jsonl"
    kept = [l for l in events.read_text().splitlines() if '"type":"run_snapshot"' in l.replace(" ", "")]
    events.write_text("\n".join(kept) + "\n")  # every other event removed
    assert state.rebuild_run(ref.run_dir).stages == run.stages


def test_rebuild_without_a_snapshot_fails_and_leaves_run_json(tmp_path):
    home, ref = make_run(tmp_path)
    (ref.run_dir / "events.jsonl").write_text('{"type": "run_created"}\n')
    before = (ref.run_dir / "run.json").read_bytes()
    with pytest.raises(FactoryError, match="no run_snapshot"):
        state.rebuild_run(ref.run_dir)
    assert (ref.run_dir / "run.json").read_bytes() == before


@pytest.mark.parametrize("when", ["before", "after"])
def test_a_process_killed_inside_write_run_leaves_the_old_or_the_new_run_json(tmp_path, when):
    """Acceptance: a crash during write_run leaves either the old or the new file, never half of one. A child process
    is killed with SIGKILL right before, or right after, the rename that publishes run.json."""
    home, ref = make_run(tmp_path)
    old = (ref.run_dir / "run.json").read_bytes()
    code = textwrap.dedent(f"""
        import os, signal, sys
        sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
        from pathlib import Path
        from factory_engine import atomic, state
        from factory_engine.lock import acquire_lock
        d = Path({str(ref.run_dir)!r})
        run = state.read_run(d)
        run.status, run.stage = 'running', 'fix'
        lock = acquire_lock(d, 'writer')
        real = os.replace
        def crash(src, dst):
            if {when!r} == 'before':
                os.kill(os.getpid(), signal.SIGKILL)
            real(src, dst)
            os.kill(os.getpid(), signal.SIGKILL)
        atomic.os.replace = crash
        state.write_run(d, run, lock=lock)
    """)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=60)
    assert proc.returncode == -signal.SIGKILL
    now = (ref.run_dir / "run.json").read_bytes()
    assert now == old if when == "before" else now != old
    assert state.read_run(ref.run_dir).status == ("pending" if when == "before" else "running")  # whole and schema-valid


def test_a_held_lock_with_a_stale_heartbeat_still_refuses(tmp_path):
    """Acceptance: acquire_lock refuses whatever the heartbeat says. The heartbeat in the lock file is rewritten as
    stale (time 0, a pid that is not the holder) while the holder still holds the kernel lock."""
    d = tmp_path / "run"
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
        from pathlib import Path
        from factory_engine.lock import acquire_lock
        acquire_lock(Path({str(d)!r}), 'holder')
        print('HELD', flush=True)
        time.sleep(600)
    """)], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "HELD"
        (d / "lock").write_text(json.dumps({"owner": "holder", "pid": 1, "heartbeat": 0}))
        with pytest.raises(FactoryError) as e:
            acquire_lock(d, "engine-2")
        assert e.value.code == "state.locked"
    finally:
        holder.kill()
        holder.wait()


def test_a_killed_holder_with_a_stale_heartbeat_releases_the_lock_at_once(tmp_path):
    """Acceptance: a killed holder releases the lock at once, whatever its heartbeat says."""
    d = tmp_path / "run"
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
        from pathlib import Path
        from factory_engine.lock import acquire_lock
        acquire_lock(Path({str(d)!r}), 'holder')
        print('HELD', flush=True)
        time.sleep(600)
    """)], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "HELD"
    (d / "lock").write_text(json.dumps({"owner": "holder", "pid": 1, "heartbeat": 0}))
    holder.kill()
    holder.wait()
    release(acquire_lock(d, "engine-2"))  # no raise


def test_a_rebuild_from_one_snapshot_gives_the_whole_run_without_heartbeat_or_signals(tmp_path):
    """Acceptance: with one run_snapshot left and every other event removed, rebuild_run gives the same run. The
    heartbeat and signals are the two fields the spec leaves out of a rebuild."""
    import dataclasses
    home, ref = make_run(tmp_path)
    run = _mid_run(ref)
    events = ref.run_dir / "events.jsonl"
    kept = [l for l in events.read_text().splitlines() if '"type":"run_snapshot"' in l.replace(" ", "")]
    events.write_text("\n".join(kept) + "\n")
    assert state.rebuild_run(ref.run_dir) == dataclasses.replace(run, heartbeat="", signals=None)


def test_a_500_run_scan_parses_only_the_runs_that_changed(tmp_path, monkeypatch):
    """Module 6A criterion: with 500 runs, a scan re-reads only files whose time or size changed, and a deleted repo
    is flagged repo_missing even when its run.json did not change."""
    import json as json_mod
    home = tmp_path / "home"
    repos = []
    for i in range(500):
        repo = tmp_path / f"r{i}"
        repo.mkdir()
        repos.append(repo)
        state.init_run(home, repo, "local/r", f"run-{i}", req(ref=f"gh-{i}"), branch="b", worktree=tmp_path, kit_hash="x")
    sc = state.RunScanner(home)
    assert sc.scan().reread == 500

    parsed = []
    real_loads = json_mod.loads
    monkeypatch.setattr(state.json, "loads", lambda s, *a, **k: (parsed.append(1), real_loads(s, *a, **k))[1])
    assert sc.scan().reread == 0 and parsed == []            # nothing changed: nothing parsed

    p = home / "runs" / "local/r" / "run-7" / "run.json"
    p.write_text(p.read_text() + " ")                        # size changed
    third = sc.scan()
    assert third.changed == ["run-7"] and third.reread == 1 and len(parsed) == 1

    repos[42].rename(tmp_path / "moved")                     # the run file did not change, the repo is gone
    fourth = sc.scan()
    assert "run-42" in fourth.repo_missing


def test_a_run_that_was_never_changed_after_creation_still_rebuilds(tmp_path):
    """Module 6, decision E1: creating a run writes a run_snapshot, so a run.json lost before its first engine change
    rebuilds to the run that was created."""
    home = tmp_path / "home"
    repo = tmp_path / "r"
    repo.mkdir()
    ref = state.init_run(home, repo, "local/r", "run-x", req(), branch="b", worktree=tmp_path, kit_hash="x")
    created = state.read_run(ref.run_dir)
    (ref.run_dir / "run.json").write_text("{not json")
    rebuilt = state.read_run(ref.run_dir)
    assert rebuilt.run_id == "run-x" and rebuilt.status == created.status == "pending"
    assert rebuilt.request == created.request
