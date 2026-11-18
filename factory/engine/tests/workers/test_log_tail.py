"""ADR 2026-11-17-worker-log-is-written-while-the-task-runs: worker.log grows while the worker runs (module 9, 12)."""

import subprocess
import sys

import pytest

from factory_engine.adapters.worker.runtime import LogTail, wait_tailing


def tail_for(tmp_path, secrets=(), render=lambda t: t):
    src = tmp_path / "out.txt"
    src.write_text("")
    return src, tmp_path / "worker.log", lambda log: LogTail(log, [(src, render)], list(secrets))


def test_new_complete_lines_are_copied_each_poll(tmp_path):
    src, log, make = tail_for(tmp_path)
    tail = make(log)
    src.write_text("one\ntwo\n")
    tail.poll()
    assert log.read_text() == "one\ntwo\n"
    with open(src, "a") as f:
        f.write("three\n")
    tail.poll()
    assert log.read_text() == "one\ntwo\nthree\n"


def test_a_partial_last_line_waits_for_its_newline(tmp_path):
    src, log, make = tail_for(tmp_path)
    tail = make(log)
    src.write_text("done\npart")
    tail.poll()
    assert log.read_text() == "done\n"
    with open(src, "a") as f:
        f.write("ial\n")
    tail.poll()
    assert log.read_text() == "done\npartial\n"


def test_a_secret_split_across_two_writes_is_never_in_the_log(tmp_path):
    secret = "sk-ABCDEF123456"
    src, log, make = tail_for(tmp_path, secrets=[secret])
    tail = make(log)
    src.write_text("token=sk-ABC")
    tail.poll()
    assert "sk-" not in log.read_text()
    with open(src, "a") as f:
        f.write("DEF123456 end\n")
    tail.poll()
    assert log.read_text() == "token=*** end\n"


def test_a_multibyte_character_cut_by_a_write_is_not_damaged(tmp_path):
    src, log, make = tail_for(tmp_path)
    tail = make(log)
    raw = "café\n".encode()
    src.write_bytes(raw[:4])  # ends inside the two-byte é
    tail.poll()
    src.write_bytes(raw)
    tail.poll()
    assert log.read_text() == "café\n"


def test_the_render_step_runs_on_complete_lines_only(tmp_path):
    src, log, make = tail_for(tmp_path, render=lambda t: t.upper())
    tail = make(log)
    src.write_text("a\nb")
    tail.poll()
    assert log.read_text() == "A\n"


def test_a_missing_capture_file_is_not_an_error(tmp_path):
    log = tmp_path / "worker.log"
    tail = LogTail(log, [(tmp_path / "none.txt", lambda t: t)], [])
    tail.poll()
    assert log.read_text() == ""


def test_the_tail_starts_from_an_empty_log(tmp_path):
    log = tmp_path / "worker.log"
    log.write_text("the last attempt\n")
    LogTail(log, [], [])
    assert log.read_text() == ""


def test_wait_tailing_copies_output_while_the_process_is_still_running(tmp_path):
    src = tmp_path / "out.txt"
    log = tmp_path / "worker.log"
    with open(src, "w") as out_f:
        proc = subprocess.Popen([sys.executable, "-u", "-c", "import time; print('first', flush=True); time.sleep(30)"],
                                stdout=out_f)
    tail = LogTail(log, [(src, lambda t: t)], [])
    seen = []

    real_poll = tail.poll

    def poll():
        real_poll()
        seen.append(log.read_text())
        if "first" in seen[-1]:
            proc.kill()

    tail.poll = poll
    wait_tailing(proc, 30, tail, interval=0.1)
    assert any("first" in s for s in seen)


def test_wait_tailing_raises_timeout_like_proc_wait(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            wait_tailing(proc, 0.3, LogTail(tmp_path / "w.log", [], []), interval=0.1)
    finally:
        proc.kill()
        proc.wait()
