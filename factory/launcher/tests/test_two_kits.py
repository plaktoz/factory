"""Two repos on different kits are driven by their own engine through one launcher (module 16, ADR
which-engine-serves-each-repo). Each repo commits a stand-in `factory_engine` whose `__main__` prints a name; the
kit snapshot is made by the real `snapshot_kit`, and every command goes through the launcher's `main`.
"""

import json
import subprocess
from pathlib import Path

import pytest

from factory_engine import api, gitops, state
from factory_engine.errors import FactoryError
from factory_launcher import cli


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                   capture_output=True)


def _repo(tmp_path: Path, name: str, *, engine: bool = True) -> Path:
    repo = tmp_path / name
    (repo / "factory").mkdir(parents=True)
    (repo / "factory" / "marker.txt").write_text(name)
    if engine:
        pkg = repo / "factory" / "engine" / "factory_engine"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "__main__.py").write_text(f"import sys\nprint('engine of {name}:', *sys.argv[1:])\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "kit")
    return repo


def _run(home: Path, repo: Path, run_id: str) -> str:
    """A run with a real kit snapshot of the repo's committed kit; returns its kit hash."""
    kit_hash = gitops.snapshot_kit(repo, "main", home)
    run_dir = home / "runs" / repo.name / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({"run_id": run_id, "repo_path": str(repo), "kit_hash": kit_hash,
                                                  "status": "blocked"}))
    return kit_hash


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(h))
    return h


def _say(capfd, argv) -> tuple[int, str, str]:
    code = cli.main(argv)
    out = capfd.readouterr()
    return code, out.out, out.err


def test_each_run_is_served_by_its_own_repos_engine(home, tmp_path, capfd):
    alpha, beta = _repo(tmp_path, "alpha"), _repo(tmp_path, "beta")
    _run(home, alpha, "run-a")
    _run(home, beta, "run-b")
    assert _say(capfd, ["status", "run-a"])[:2] == (0, "engine of alpha: status run-a --repo " + str(alpha) + "\n")
    assert _say(capfd, ["status", "run-b"])[:2] == (0, "engine of beta: status run-b --repo " + str(beta) + "\n")


def test_a_run_keeps_its_engine_after_the_repos_kit_changes(home, tmp_path, capfd):
    alpha = _repo(tmp_path, "alpha")
    _run(home, alpha, "run-a")
    (alpha / "factory" / "engine" / "factory_engine" / "__main__.py").write_text("print('engine of alpha v2')\n")
    _git(alpha, "commit", "-q", "-am", "upgrade the kit")
    assert _say(capfd, ["status", "run-a"])[1].startswith("engine of alpha:")


def test_a_command_that_creates_a_run_uses_the_repos_committed_engine(home, tmp_path, capfd):
    beta = _repo(tmp_path, "beta")
    code, out, _ = _say(capfd, ["sync", "--repo", str(beta)])
    assert code == 0 and out.startswith("engine of beta: sync")


def test_a_pythonpath_already_set_stays_after_the_engine_path(home, tmp_path, monkeypatch):
    alpha = _repo(tmp_path, "alpha")
    kit_hash = _run(home, alpha, "run-a")
    monkeypatch.setenv("PYTHONPATH", "/somewhere/else")
    env = api.run_engine_env(alpha, "run-a")
    assert env["PYTHONPATH"].split(":") == [str(home / "kits" / kit_hash / "factory" / "engine"), "/somewhere/else"]


@pytest.mark.parametrize("command", [["status", "run-a"], ["abort", "run-a"]])
def test_a_run_whose_kit_has_no_engine_starts_nothing_and_fails_with_kit_no_engine(home, tmp_path, capfd, monkeypatch,
                                                                                  command):
    old = _repo(tmp_path, "old", engine=False)
    _run(home, old, "run-a")
    started: list = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: started.append(a))
    code, out, _ = _say(capfd, [*command, "--json"])
    assert code == 2 and started == []
    doc = json.loads(out)
    assert doc["ok"] is False and doc["code"] == "kit.no_engine" and "run-a" in doc["message"]
    assert "--installed-engine" in doc["hint"]


@pytest.mark.parametrize("command", [["status", "run-a"], ["abort", "run-a"]])
def test_installed_engine_runs_that_one_command_on_the_installed_engine(home, tmp_path, capfd, monkeypatch, command):
    old = _repo(tmp_path, "old", engine=False)
    _run(home, old, "run-a")
    seen: list = []
    monkeypatch.setattr(cli.subprocess, "run", lambda argv, **k: seen.append(k["env"]) or subprocess.CompletedProcess(argv, 0))
    assert cli.main([*command, "--installed-engine"]) == 0
    assert len(seen) == 1 and "PYTHONPATH" not in seen[0]


def test_an_engine_started_by_tick_is_the_runs_own(home, tmp_path, monkeypatch):
    alpha = _repo(tmp_path, "alpha")
    kit_hash = _run(home, alpha, "run-a")
    seen: list = []

    class _Proc:
        pid = 7

    monkeypatch.setattr(api.subprocess, "Popen", lambda argv, **k: seen.append(k["env"]) or _Proc())
    assert api.spawn_engine(alpha, "run-a") == 7
    assert seen[0]["PYTHONPATH"].split(":")[0] == str(home / "kits" / kit_hash / "factory" / "engine")


def test_tick_does_not_start_a_run_whose_kit_has_no_engine(home, tmp_path, monkeypatch):
    old = _repo(tmp_path, "old", engine=False)
    _run(home, old, "run-a")
    started: list = []
    monkeypatch.setattr(api.subprocess, "Popen", lambda *a, **k: started.append(a))
    with pytest.raises(FactoryError) as err:
        api.spawn_engine(old, "run-a")
    assert err.value.code == "kit.no_engine" and started == []
