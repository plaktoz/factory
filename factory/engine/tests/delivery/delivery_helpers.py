"""Helpers for module 13 tests: a repo with a bare remote, a run with a kit snapshot, and run-state setters."""

from __future__ import annotations

import subprocess
from pathlib import Path

from factory_engine import gitops, state
from factory_engine.config import Config
from factory_engine.lock import acquire_lock, release
from factory_engine.types import Request, Source, StageState

GIT_ID = ["-c", "user.name=test", "-c", "user.email=test@example.invalid"]

POLICY = """default: human
auto:
  workflows: [chore]
  type_source: [explicit, label, front_matter]
  require: {gates: all_passed, ci: green, max_files: 10, max_lines: 300}
never_auto_if:
  paths: ["**/migrations/**", "auth/**", "infra/**", ".github/**", "factory/**", ".factory/config/**"]
  dependency_manifests_changed: true
  architecture_decision: true
  review_findings_at_or_above: medium
  notes_used: true
  rework_loops_used_at_least: 2
"""

CHORE = "name: chore\ntype: chore\nsink: pull_request\npolicy: {write: true}\nstages: []\n"
RESEARCH = "name: research\ntype: research\nsink: doc\npolicy: {write: false}\nstages: []\n"
ASK = "name: ask\ntype: ask\nsink: comment\npolicy: {write: false}\nstages: []\n"


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *GIT_ID, "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return r.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    src = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    (src / "app").mkdir()
    (src / "app" / "main.py").write_text("x = 1\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "init")
    git(src, "remote", "add", "origin", str(bare))
    git(src, "push", "-q", "origin", "main")
    return src


def make_cfg(tmp_path: Path) -> Config:
    return Config(machine={"worktree_root": str(tmp_path / "wt"), "worktree_path": "{root}/{repo}/{run_id}"},
                  repo={"base_branch": "main"})


def make_run(home: Path, tmp_path: Path, cfg: Config, *, workflow="chore", write=True, type_source="explicit",
             source_type="cli", ref="note.md", source_files=(), kit_files: dict[str, str] | None = None,
             run_id="tidy-ab12c"):
    """A run with a real worktree, a kit snapshot holding the policy and the workflows, and a state of `running`.
    Returns (run_dir, worktree, repo)."""
    repo = make_repo(tmp_path)
    wt = gitops.create_run_worktree(repo, cfg, run_id, base="main", detached=not write)
    src = Source(source_type, ref, "t", "b", [], None, [Path(f) for f in source_files])
    request = Request("r-1", src, "sha", "repo", "Tidy the app", "chore", type_source, None, [])
    ref_ = state.init_run(home, repo, "local/repo", run_id, request, branch=run_id if write else None, worktree=wt,
                          kit_hash="kit1")
    kit = home / "kits" / "kit1"
    files = {".factory/config/merge-policy.yaml": POLICY, "factory/workflows/chore.yaml": CHORE,
             "factory/workflows/research.yaml": RESEARCH, "factory/workflows/ask.yaml": ASK, **(kit_files or {})}
    for rel, text in files.items():
        (kit / rel).parent.mkdir(parents=True, exist_ok=True)
        (kit / rel).write_text(text)
    set_run(ref_.run_dir, workflow=workflow, status="running",
            stages=[StageState("implement", 1, "done", ["change"], "t0", "t1")])
    return ref_.run_dir, wt, repo


def set_run(run_dir: Path, **fields) -> None:
    run = state.read_run(run_dir)
    for k, v in fields.items():
        setattr(run, k, v)
    lock = acquire_lock(run_dir, "test")
    state.write_run(run_dir, run, lock=lock)
    release(lock)


def write_task(run_dir: Path, task_id: str, status: str) -> None:
    from factory_engine.types import TaskState
    lock = acquire_lock(run_dir, "test")
    state.write_task(run_dir, TaskState(task_id, "implement", status, 1, 0, None, None, 0), lock=lock)
    release(lock)


def commit_change(wt: Path, files: dict[str, str], message: str = "change") -> None:
    for rel, text in files.items():
        (wt / rel).parent.mkdir(parents=True, exist_ok=True)
        (wt / rel).write_text(text)
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", message)


def pass_gates(run_dir: Path, *gates: str) -> None:
    for g in gates:
        state.append_event(run_dir, "gate_passed", gate=g, code="ok", exit_code=None)
