"""The bug-fix fixture (bugfix-target/, next to this file): what a live run needs from it, checked without a model.

Each test copies the fixture into a temporary git repo and runs the workflow's commands the way the engine does: an
argument list, in the repo root, with the engine's base environment and a task folder in FACTORY_TASK_DIR. Nothing here
calls a model, starts a worker, runs `factory`, or runs under the sandbox (srt). They are plain subprocesses.
"""

import fnmatch
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from factory_engine import gates, kit
from factory_engine.adapters.worker.runtime import base_env, cache_env

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "bugfix-target"
KIT_DIR = HERE.parents[2]  # factory/: the kit folder that init copies into a target repo (HERE is factory/engine/tests/fixtures)
WORKFLOW = KIT_DIR / "workflows" / "bug-fix.yaml"
GIT = ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid"]


@pytest.fixture
def repo(tmp_path):
    """The fixture as a git repo with one commit, the way a seeded GitHub repo starts."""
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    subprocess.run([*GIT, "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=root, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "seed the report total bug"], cwd=root, check=True)
    return root


def run(repo: Path, argv: list[str], task_id: str, tmp_path: Path):
    """Run one command as the engine runs a cmd task: argv, cwd the repo root, FACTORY_TASK_DIR set. Returns the
    process and the task folder, where a JUnit file would be."""
    task_dir = tmp_path / "tasks" / task_id / "work"
    task_dir.mkdir(parents=True, exist_ok=True)
    env = base_env(os.environ)
    env.update({"FACTORY_RUN_ID": "fixture-test", "FACTORY_STAGE": "verify", "FACTORY_TASK_ID": task_id,
                "FACTORY_WORKTREE": str(repo), "FACTORY_TASK_DIR": str(task_dir),
                # make and the repro scripts use this interpreter, the one that has pytest installed.
                "PYTHON": os.environ.get("FIXTURE_PYTHON", os.sys.executable)})
    env.update(cache_env(task_dir))
    proc = subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True, timeout=300)
    return proc, task_dir


def junit_cases(path: Path) -> int:
    """The test cases the engine's own JUnit reader counts in a report file."""
    assert path.is_file(), f"no JUnit file at {path}"
    return gates.parse_junit([path]).total


def test_with_the_bug_present_the_gates_and_test_api_fail_the_way_the_workflow_expects(repo, tmp_path):
    report = (repo / "services" / "api" / "report.py").read_text()
    assert "rows[:-1]" in report, "the seeded bug is in the tree (fix.patch is not applied by default)"

    # reproduce gate: the command exits 0 while the bug reproduces
    proc, _ = run(repo, ["scripts/repro-fails.sh"], "repro", tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # verify gate: the same check must fail while the bug is there
    proc, _ = run(repo, ["scripts/repro-now-passes.sh"], "verify", tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr

    # be-tests: fails, and its JUnit file names the failing case
    proc, task = run(repo, ["make", "test-api"], "be-tests", tmp_path)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    be = gates.parse_junit([task / "be.junit.xml"])
    assert be.total >= 1 and be.failed, "the bug shows as a failing JUnit case"

    # build and fe-tests do not depend on the bug: the frontend is right and build is a syntax check
    proc, _ = run(repo, ["make", "build"], "build", tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc, _ = run(repo, ["npm", "--prefix", "web", "test"], "fe-tests", tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_after_the_one_line_fix_every_command_exits_as_the_workflow_wants(repo, tmp_path):
    subprocess.run(["git", "apply", "fix.patch"], cwd=repo, check=True)
    assert (repo / "services" / "api" / "report.py").read_text().count("rows[:-1]") == 0

    # The reproduce gate runs only before the fix. After it, the check reports the bug gone (exit 1 here), which
    # is the state the verify gate needs: scripts/repro-now-passes.sh exits 0 below.
    proc, _ = run(repo, ["scripts/repro-fails.sh"], "repro", tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr

    proc, _ = run(repo, ["make", "build"], "build", tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    proc, be_dir = run(repo, ["make", "test-api"], "be-tests", tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert junit_cases(be_dir / "be.junit.xml") >= 1
    assert gates.parse_junit([be_dir / "be.junit.xml"]).failed == []

    proc, fe_dir = run(repo, ["npm", "--prefix", "web", "test"], "fe-tests", tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert junit_cases(fe_dir / "fe.junit.xml") >= 1

    proc, e2e_dir = run(repo, ["make", "e2e"], "e2e", tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert junit_cases(e2e_dir / "e2e.junit.xml") >= 1

    proc, _ = run(repo, ["scripts/repro-now-passes.sh"], "verify", tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_fixture_has_no_github_folder_no_deny_path_and_no_reference_to_this_repos_docs():
    files = sorted(p.relative_to(FIXTURE).as_posix() for p in FIXTURE.rglob("*") if p.is_file())
    assert files, "the fixture has files"
    assert not (FIXTURE / ".github").exists()
    assert not [f for f in files if ".github" in f.split("/")]

    deny = yaml.safe_load(WORKFLOW.read_text())["policy"]["deny_paths"]
    hits = [(f, d) for f in files for d in deny if fnmatch.fnmatch(f, d)]
    assert hits == [], f"files the workflow's deny_paths refuse: {hits}"

    for f in files:
        text = (FIXTURE / f).read_text(errors="replace")
        assert "docs/" not in text and "AGENTS.md" not in text, f"{f} refers to this repo's docs"


def test_the_kit_copy_leaves_the_fixture_out():
    """init and upgrade copy factory/ into a target repo. The fixture is under factory/engine/tests, which they skip."""
    assert FIXTURE.is_relative_to(KIT_DIR / "engine" / "tests")
    copied = kit._kit_files(KIT_DIR)
    assert not [k for k in copied if k.startswith("engine/tests/")]
