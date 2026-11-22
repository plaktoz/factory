"""`factory gc` (module 16): shows the housekeeping plan, and only `--apply` carries it out.

The repo is a plain folder with no remote, so no push runs. An empty factory home has nothing to clean, so the
tests check the command's answer: the `--json` shape, the plan-only wording, and that `--apply` is the only switch.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from factory_engine import cli
from factory_engine.errors import EXIT_OK

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "housekeeping"))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    return r


def _gc(argv, capsys):
    code = cli.main(["gc", *argv])
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    return code, (json.loads(lines[-1]) if lines and lines[-1].startswith("{") else None)


def test_gc_without_apply_is_a_plan_only_and_says_so(repo, capsys):
    code, doc = _gc(["--repo", str(repo), "--json"], capsys)

    assert code == EXIT_OK
    assert doc["ok"] is True
    assert doc["data"]["applied"] is False
    assert doc["message"].startswith("plan only")


def test_gc_with_apply_reports_that_it_applied(repo, capsys):
    code, doc = _gc(["--repo", str(repo), "--apply", "--json"], capsys)

    assert code == EXIT_OK
    assert doc["data"]["applied"] is True
    assert doc["message"].startswith("applied")


def test_gc_json_lists_items_and_skipped_runs_as_lists(repo, capsys):
    _, doc = _gc(["--repo", str(repo), "--json"], capsys)

    assert doc["data"]["items"] == []
    assert doc["data"]["skipped"] == []


def test_gc_json_says_why_a_worktree_was_skipped_when_gh_cannot_be_read(repo, capsys, monkeypatch):
    """Issue 86: a `gh` failure keeps the worktree, and the --json output carries gh's own message."""
    from factory_engine import api, gitops, state
    from factory_engine.clock import SystemClock
    from factory_engine.gh import GitHubPullRequests
    from factory_engine.loadcfg import load_config
    from factory_engine.types import PrRef
    from housekeeping_helpers import days_ago, make_run, set_event_times

    monkeypatch.setenv("FACTORY_WORKTREE_ROOT", str(repo.parent / "wt"))
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    cfg = load_config(repo)
    wt = gitops.create_run_worktree(repo, cfg, "r1", base="main", detached=False)
    ended = days_ago(SystemClock(), 8)
    run_dir = make_run(state.factory_home(), repo, "r1", status="done", worktree=wt, ended=ended)
    run = state.read_run(run_dir)
    run.pr = PrRef(number=1, url="u", head="r1", base="main")
    lock = state.acquire_lock(run_dir, "test"); state.write_run(run_dir, run, lock=lock); state.release(lock)
    set_event_times(run_dir, ended)
    no_auth = lambda args: subprocess.CompletedProcess(args, 1, "", "To get started with GitHub CLI, please run:  gh auth login")
    monkeypatch.setattr(api, "default_prs", lambda repo, cfg: GitHubPullRequests(runner=no_auth))

    _, doc = _gc(["--repo", str(repo), "--apply", "--json"], capsys)

    assert wt.exists()
    [s] = [s for s in doc["data"]["skipped"] if s["path"] == str(wt)]
    assert s["reason"] == "pull request cannot be read" and "gh auth login" in s["detail"]
