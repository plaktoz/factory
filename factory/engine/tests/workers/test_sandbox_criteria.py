"""Module 9 sandbox acceptance criteria, against the real `srt`: rows 312, 314, 315, 320 and 321.

They use the real CommandAdapter and a layout that matches a real run: a FACTORY_HOME holding the run folder, the task
folder (task.json, notes.jsonl, work/) and the worktree, with the home itself denied to the worker. They skip without
srt 0.0.83 and Node 22.12 or later, as the other srt tests do. Every path is under a temp FACTORY_HOME, so the real
~/.factory is never touched.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from factory_engine import notes, state
from factory_engine.adapters.worker import sandbox
from factory_engine.adapters.worker.command import CommandAdapter
from factory_engine.types import TaskState

from workers_helpers import harness

SRT = shutil.which("srt")
needs_srt = pytest.mark.skipif(SRT is None or sandbox.node_version() is None or sandbox.node_version()[:2] < (22, 12),
                               reason="srt 0.0.83 and Node 22.12+ are required (module 9)")


@pytest.fixture
def layout(tmp_path, monkeypatch):
    """runs/<key>/<run>/tasks/backend/{task.json, notes.jsonl, work/} beside a worktree, all under one FACTORY_HOME."""
    home = tmp_path / "factory-home"
    home.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(home))
    run_dir = home / "runs" / "key" / "run-1"
    run_dir.mkdir(parents=True)
    task_root = run_dir / "tasks" / "backend"
    task_dir = task_root / "work"
    task_dir.mkdir(parents=True)
    worktree = home / "worktrees" / "run-1--backend"
    worktree.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(worktree)], check=True)
    return {"home": home, "run_dir": run_dir, "task_root": task_root, "task_dir": task_dir, "worktree": worktree}


def run_cmd(layout, cmd, tmp_path, timeout=60):
    """One real command attempt: the worktree is its cwd and work/ its task folder, both under the denied home."""
    from factory_engine.adapters.worker.base import TaskContext
    ctx = TaskContext(run_id="run-1", task_id="backend", stage="fix", attempt=1, skill=None, request=None,
                      worktree=layout["worktree"], task_dir=layout["task_dir"], scope=["src/**"], deny=[],
                      helpers=None, feedback=[], notes=[], progress=None, output_schema=None, model=None, mcp=[],
                      practices=[], cmd=list(cmd), artifact_name="out.json")
    adapter = CommandAdapter(dict(os.environ))
    log = tmp_path / f"worker-{len(list(tmp_path.glob('worker-*.log')))}.log"  # one log per run, so none is overwritten
    handle = adapter.start(ctx, harness("command"), log)
    return adapter.wait(handle, timeout), log


def write_engine_state(layout):
    """The engine's own state for the task, written under the run lock and read back through the engine's reader."""
    lock = state.acquire_lock(layout["run_dir"], "engine-test")
    try:
        t = TaskState(task_id="backend", stage="fix", status="pending", attempt=1, restarts=0, task_base=None,
                      worktree=layout["worktree"], checkpoints=0)
        state.write_task(layout["run_dir"], t, lock=lock)
        notes.queue_note(layout["run_dir"], "backend", "original note", by="me")
    finally:
        state.release(lock)


# ---- row 312: the worker cannot change engine state outside work/, and the engine reads the originals ---------------

@needs_srt
def test_a_worker_cannot_change_task_json_or_notes_and_the_engine_reads_the_originals(layout, tmp_path):
    write_engine_state(layout)
    task_json = layout["task_root"] / "task.json"
    notes_file = layout["task_root"] / "notes.jsonl"
    before = (task_json.read_text(), notes_file.read_text())
    before_state = state.read_task(layout["run_dir"], "backend")
    before_notes = [n.text for n in notes.pending_notes(layout["run_dir"], "backend")]
    run_json = layout["run_dir"] / "run.json"
    run_json.write_text('{"run_id": "run-1"}\n')

    r1, _ = run_cmd(layout, ["sh", "-c", f"echo forged > {task_json}"], tmp_path)
    r2, _ = run_cmd(layout, ["sh", "-c", f"echo forged >> {notes_file}"], tmp_path)
    r3, _ = run_cmd(layout, ["sh", "-c", f"echo forged > {run_json}"], tmp_path)

    assert (r1.exit, r2.exit, r3.exit) == ("failed", "failed", "failed")
    assert (task_json.read_text(), notes_file.read_text()) == before
    assert run_json.read_text() == '{"run_id": "run-1"}\n'
    assert state.read_task(layout["run_dir"], "backend") == before_state
    assert [n.text for n in notes.pending_notes(layout["run_dir"], "backend")] == before_notes


# ---- row 314: the sandboxed worker reads its progress and runs git; the canary in the factory home is denied ------

@needs_srt
def test_a_sandboxed_command_cannot_read_a_canary_in_the_factory_home_but_reads_its_progress(layout, tmp_path):
    canary = layout["home"] / "canary-secret.txt"
    canary.write_text("CANARY-VALUE\n")
    progress = layout["task_dir"] / "progress.md"
    progress.write_text("step two done\n")

    cat_canary, cat_log = run_cmd(layout, ["cat", str(canary)], tmp_path)
    py_canary, py_log = run_cmd(layout, [sys.executable, "-c", f"print(open({str(canary)!r}).read())"], tmp_path)
    cat_progress, progress_log = run_cmd(layout, ["cat", str(progress)], tmp_path)

    assert cat_canary.exit == "failed" and cat_canary.exit_code != 0
    assert py_canary.exit == "failed" and py_canary.exit_code != 0
    assert "CANARY-VALUE" not in cat_log.read_text() and "CANARY-VALUE" not in py_log.read_text()
    assert cat_progress.exit == "ok" and "step two done" in progress_log.read_text()


@needs_srt
def test_git_status_diff_and_add_work_in_the_task_worktree_under_the_sandbox(layout, tmp_path):
    wt = layout["worktree"]
    subprocess.run(["git", "-C", str(wt), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "base"], check=True)
    (wt / "f.txt").write_text("one\n")
    subprocess.run(["git", "-C", str(wt), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(wt), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "add"],
                   check=True)
    (wt / "f.txt").write_text("two\n")

    status, s_log = run_cmd(layout, ["git", "status", "--short"], tmp_path)
    diff, d_log = run_cmd(layout, ["git", "diff", "--stat"], tmp_path)
    add, _ = run_cmd(layout, ["git", "add", "f.txt"], tmp_path)

    assert (status.exit, diff.exit, add.exit) == ("ok", "ok", "ok")
    assert "M f.txt" in s_log.read_text()
    assert "f.txt" in d_log.read_text()


# ---- row 320: a cmd task runs under srt; shell syntax in an argument is one argument; exit codes arrive unchanged ----

@needs_srt
def test_a_cmd_argument_with_shell_syntax_reaches_the_program_as_one_argument_and_creates_no_file(layout, tmp_path):
    """`c;touch X` and `$(touch Y)` are passed as arguments to a Python program that prints its argv as JSON. Each one
    must come back as the single string it was, and neither marker file may exist afterwards."""
    marker_x = layout["worktree"] / "X"
    marker_y = layout["worktree"] / "Y"
    argv_probe = [sys.executable, "-c", "import json,sys; print(json.dumps(sys.argv[1:]))",
                  f"c;touch {marker_x}", f"$(touch {marker_y})", "a b"]
    result, log = run_cmd(layout, argv_probe, tmp_path)
    assert result.exit == "ok", log.read_text()
    received = json.loads(log.read_text().strip().splitlines()[-1])
    assert received == [f"c;touch {marker_x}", f"$(touch {marker_y})", "a b"]
    assert not marker_x.exists() and not marker_y.exists()


@needs_srt
@pytest.mark.parametrize("code", [0, 3, 127])
def test_a_cmd_exit_code_arrives_unchanged_through_srt(layout, tmp_path, code):
    result, _ = run_cmd(layout, ["sh", "-c", f"exit {code}"], tmp_path)
    assert result.exit_code == code
    assert result.exit == ("ok" if code == 0 else "failed")


# ---- row 321: a tool's cache goes under the task's work/ folder, and a write to a home cache still fails ----------

@needs_srt
@pytest.mark.skipif(shutil.which("npm") is None, reason="npm is not installed")
def test_npm_writes_its_cache_under_the_task_folder_and_a_write_to_home_npm_fails(layout, tmp_path, monkeypatch):
    """A real npm run reports its cache under work/cache/npm. A write to the home's ~/.npm is refused."""
    home = tmp_path / "userhome"
    (home / ".npm").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    report, log = run_cmd(layout, ["npm", "config", "get", "cache"], tmp_path)
    blocked, _ = run_cmd(layout, ["sh", "-c", f"echo x > {home / '.npm' / 'probe'}"], tmp_path)
    assert report.exit == "ok", log.read_text()
    assert log.read_text().strip() == str(layout["task_dir"] / "cache" / "npm")
    assert blocked.exit == "failed"
    assert not (home / ".npm" / "probe").exists()


@needs_srt
@pytest.mark.skipif(shutil.which("go") is None, reason="go is not installed")
def test_go_build_writes_its_cache_under_the_task_folder(layout, tmp_path):
    """A real `go build` writes its build cache to work/cache/go-build and nowhere else."""
    wt = layout["worktree"]
    (wt / "go.mod").write_text("module example.com/probe\n\ngo 1.21\n")
    (wt / "main.go").write_text("package main\n\nfunc main() { println(\"hi\") }\n")
    result, log = run_cmd(layout, ["go", "build", "-o", "/dev/null", "."], tmp_path)
    assert result.exit == "ok", log.read_text()
    assert (layout["task_dir"] / "cache" / "go-build").is_dir()


@needs_srt
@pytest.mark.skipif(shutil.which("mvn") is None, reason="mvn is not installed")
def test_maven_writes_its_repository_under_the_task_folder(layout, tmp_path):
    """A real offline `mvn validate` on a pom with no dependencies writes its local repository under work/cache/m2."""
    (layout["worktree"] / "pom.xml").write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>'
        "<groupId>x</groupId><artifactId>probe</artifactId><version>1</version><packaging>pom</packaging></project>")
    result, log = run_cmd(layout, ["mvn", "-o", "-B", "validate"], tmp_path)
    assert result.exit == "ok", log.read_text()
    assert (layout["task_dir"] / "cache" / "m2").is_dir()


# ---- row 315: a write outside the worktree and the task folder fails, including srt's built-in temp path ------------

@needs_srt
@pytest.mark.xfail(strict=True, reason="defect: srt 0.0.83 always allows /tmp/claude; denying it breaks go build "
                                       "(go writes its work dir there, even with GOTMPDIR set). Open decision, module 9.")
def test_a_command_cannot_write_to_srts_builtin_temp_path_outside_the_worktree_and_task_folder(layout, tmp_path):
    """srt always allows writes under /tmp/claude (sandbox-runtime, defaultWritePathsUnder), so the settings must deny
    it. A command must not be able to write there, because that path is outside both the worktree and work/."""
    builtin = Path("/private/tmp/claude")
    if not builtin.parent.is_dir():
        pytest.skip("this machine has no /private/tmp")
    probe = builtin / f"factory-probe-{os.getpid()}.txt"
    try:
        result, _ = run_cmd(layout, ["sh", "-c", f"echo x > {probe}"], tmp_path)
        assert result.exit == "failed" and not probe.exists()
    finally:
        probe.unlink(missing_ok=True)
