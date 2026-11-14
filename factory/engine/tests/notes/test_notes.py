"""Module 12 acceptance criteria."""

import pytest

from factory_engine import notes, state
from factory_engine.errors import FactoryError
from factory_engine.gitops import check_scope_diff_paths
from factory_engine.lock import acquire_lock, release
from factory_engine.state import init_run
from factory_engine.types import Request, Source, TaskState


def make(tmp_path, status="running"):
    src = Source("github", "acme/report#1", "t", "b", [], "a", [])
    rq = Request("gh-1", src, "sha", "report", "t", "bug", "label", "high", [])
    repo = tmp_path / "report"
    repo.mkdir()
    ref = init_run(tmp_path / "home", repo, "github.com/acme/report", "run-1", rq, branch="run-1", worktree=tmp_path / "wt", kit_hash="x")
    lock = acquire_lock(ref.run_dir, "e")
    state.write_task(ref.run_dir, TaskState("backend", "fix", status, 1, 0, None, None, 0), lock=lock)
    release(lock)
    return ref.run_dir


def test_a_queued_note_is_pending_until_delivered_then_appears_in_every_later_prompt(tmp_path):
    rd = make(tmp_path)
    ref = notes.queue_note(rd, "backend", "use the v2 client", by="me")
    assert [n.text for n in notes.pending_notes(rd, "backend")] == ["use the v2 client"]
    assert notes.delivered_notes(rd, "backend") == []
    notes.mark_delivered(rd, "backend", [ref.note_id], attempt=2)
    assert notes.pending_notes(rd, "backend") == []
    assert notes.delivered_notes(rd, "backend") == ["use the v2 client"]
    later = notes.queue_note(rd, "backend", "and add a test", by="me")
    notes.mark_delivered(rd, "backend", [later.note_id], attempt=3)
    assert notes.delivered_notes(rd, "backend") == ["use the v2 client", "and add a test"]
    types = [e.type for e in state.read_events(rd)]
    assert types.count("note_queued") == 2 and types.count("note_delivered") == 2


def test_marking_a_delivered_note_again_changes_nothing(tmp_path):
    rd = make(tmp_path)
    ref = notes.queue_note(rd, "backend", "x", by="me")
    notes.mark_delivered(rd, "backend", [ref.note_id], attempt=2)
    notes.mark_delivered(rd, "backend", [ref.note_id], attempt=3)
    assert [e.type for e in state.read_events(rd)].count("note_delivered") == 1


def test_a_note_with_deny_makes_the_scope_check_fail_on_a_later_edit(tmp_path):
    rd = make(tmp_path)
    notes.queue_note(rd, "backend", "keep out of auth", deny=["auth/**"], by="me")
    deny = [d for n in notes.pending_notes(rd, "backend") for d in n.deny]
    assert check_scope_diff_paths(["auth/login.py", "api/x.py"], ["**"], deny) == ["auth/login.py"]
    assert check_scope_diff_paths(["api/x.py"], ["**"], deny) == []


@pytest.mark.parametrize("status", ["done", "failed"])
def test_a_note_for_a_finished_task_is_refused_with_a_clear_message(tmp_path, status):
    rd = make(tmp_path, status)
    with pytest.raises(FactoryError) as e:
        notes.queue_note(rd, "backend", "too late", by="me")
    assert e.value.code == "notes.task_finished" and "backend" in str(e.value) and status in str(e.value)
    assert notes.pending_notes(rd, "backend") == []


def test_tail_log_returns_the_last_lines_without_reading_the_whole_file(tmp_path, monkeypatch):
    log = tmp_path / "worker.log"
    log.write_text("".join(f"line {i}\n" for i in range(200_000)))
    sizes = []
    real_open = type(log).open

    def spy(self, *a, **k):
        f = real_open(self, *a, **k)
        orig = f.read

        def read(n=-1):
            sizes.append(n)
            return orig(n)

        f.read = read
        return f

    monkeypatch.setattr(type(log), "open", spy)
    assert notes.tail_log(log, 3) == "line 199997\nline 199998\nline 199999\n"
    assert sizes and all(0 < n <= 8192 for n in sizes)


def test_tail_log_handles_short_missing_and_non_utf8_files(tmp_path):
    log = tmp_path / "w.log"
    assert notes.tail_log(log) == ""
    log.write_bytes(b"a\nb\xff\n")
    assert notes.tail_log(log, 200) == "a\nb�\n"
    assert notes.tail_log(log, 1) == "b�\n"
