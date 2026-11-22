"""D8 (owner decision 2026-11-22): the engine formats a task's changed files once, after its worker has stopped and
before the final commit (module 17A, "Where lint and format run", step 1). Stub tools stand in for the formatters."""

import os
import stat

import pytest

from factory_engine import gitops, state
from factory_engine.adapters.worker.fake import ok

from engine_helpers import chore_script

RUN = "bump-q1w2e"


def _stub(bin_dir, name, body):
    bin_dir.mkdir(exist_ok=True)
    p = bin_dir / name
    p.write_text(f"#!/bin/sh\n{body}\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def stubs(tmp_path, monkeypatch):
    bins = tmp_path / "bin"
    monkeypatch.setenv("PATH", f"{bins}{os.pathsep}{os.environ['PATH']}")
    return bins


def _worker_writes(worker, files):
    real_start = worker.start

    def start(ctx, conf, log):
        if ctx.task_id == "change":
            for rel, text in files.items():
                (ctx.worktree / rel).parent.mkdir(parents=True, exist_ok=True)
                (ctx.worktree / rel).write_text(text)
        return real_start(ctx, conf, log)

    worker.start = start


def _run(new_run, engine, files, ruff_body, stubs):
    _stub(stubs, "ruff", ruff_body)
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * 4)
    eng, worker = engine(script, writes)
    _worker_writes(worker, files)
    eng.run([RUN])
    return run_dir, state.read_run(run_dir)


FORMAT_OR_PASS = 'if [ "$1" = format ] && [ "$2" != --check ]; then shift; for f in "$@"; do echo formatted > "$f"; done; fi'


def test_the_tasks_final_commit_holds_formatted_code_and_notes_stay_out(new_run, engine, stubs):
    run_dir, run = _run(new_run, engine, {"pyproject.toml": "[project]\n", "services/new.py": "x=1\n", "NOTES.txt": "raw\n"},
                        FORMAT_OR_PASS, stubs)
    show = lambda path: gitops.git(run.worktree, "show", f"{RUN}:{path}").stdout  # noqa: E731
    assert show("services/new.py") == "formatted\n"
    assert show("NOTES.txt") == "raw\n"                       # no profile owns a .txt file
    assert any(e.type == "task_formatted" and e.data["task_id"] == "change" and e.data["files"] == ["services/new.py"]
               for e in state.read_events(run_dir))


def test_a_formatter_that_fails_fails_the_attempt_and_the_unformatted_file_is_not_committed(new_run, engine, stubs):
    run_dir, run = _run(new_run, engine, {"pyproject.toml": "[project]\n", "services/new.py": "x=1\n"},
                        'if [ "$1" = format ] && [ "$2" != --check ]; then echo boom; exit 2; fi', stubs)
    assert run.status == "blocked"
    assert gitops.git(run.worktree, "ls-tree", "-r", "--name-only", RUN).stdout.count("services/new.py") == 0
    assert state.read_task(run_dir, "change").status == "failed"


def test_a_cmd_task_is_never_formatted_even_when_it_writes_a_python_file(new_run, engine, stubs, tmp_path):
    """A cmd task writes its own files (17A: formatting is for a worker's files). Its .py output must stay unformatted."""
    marker = tmp_path / "ruff-ran-on"
    run_dir = new_run()
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    _stub(stubs, "ruff", f'if [ "$1" = format ] && [ "$2" != --check ]; then echo "$@" >> {marker}; fi')
    script, writes = chore_script(run_dir, change=[ok(work("change", "change.json"))] * 4)
    eng, worker = engine(script, writes)
    _worker_writes(worker, {"pyproject.toml": "[project]\n", "services/new.py": "x=1\n"})  # the worker's file: formatted
    real_start = worker.start

    def check_writes_py(ctx, conf, log):
        if ctx.task_id == "check":
            (ctx.worktree / "generated.py").write_text("x=1\n")
        return real_start(ctx, conf, log)

    worker.start = check_writes_py
    eng.run([RUN])
    formatted = marker.read_text().splitlines()
    assert formatted == ["format services/new.py"]     # the worker's file, once; the cmd task's generated.py is not formatted


def test_a_worker_that_restarts_to_deliver_a_note_has_its_files_formatted_before_the_restart(new_run, engine, stubs):
    """17A step 1: formatting runs at the end of an attempt, and before a restart that delivers a note."""
    run_dir, run = _run(new_run, engine, {"pyproject.toml": "[project]\n", "services/new.py": "x=1\n"}, FORMAT_OR_PASS, stubs)
    assert any(e.type == "task_formatted" and e.data["task_id"] == "change" for e in state.read_events(run_dir))
