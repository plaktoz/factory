"""Two repos on different kit versions are driven by their own engine through one launcher (module 16, ADR 2026-11-20-which-engine-serves-each-repo).

Each repo's engine is a stand-in `factory_engine` whose __main__ prints its own name, so the test can see which
engine answered. The launcher's installed engine is the real one, so a test that passes proves the snapshot ran.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from factory_launcher import cli

STAND_IN_MAIN = 'import sys\nprint("ENGINE", {name!r}, sys.argv[1:])\n'


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _stand_in(folder: Path, name: str) -> None:
    """A minimal factory_engine package that prints its name and its argv. Replaces any package already there."""
    pkg = folder / "factory_engine"
    if pkg.exists():
        import shutil
        shutil.rmtree(pkg)
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text(STAND_IN_MAIN.format(name=name))


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(h))
    return h


def _repo(tmp_path: Path, name: str, engine_name: str) -> Path:
    """A git repo whose committed factory/engine is a stand-in engine named `engine_name`."""
    r = tmp_path / name
    r.mkdir()
    _git("init", "-q", cwd=r)
    _git("config", "user.email", "t@example.com", cwd=r)
    _git("config", "user.name", "t", cwd=r)
    _stand_in(r / "factory" / "engine", engine_name)
    _git("add", "-A", cwd=r)
    _git("commit", "-q", "-m", "kit", cwd=r)
    return r


def _snapshot(home: Path, kit_hash: str, engine_name: str | None) -> None:
    """What snapshot_kit leaves for a kit: kits/<hash>/factory/engine, or no engine folder at all."""
    base = home / "kits" / kit_hash / "factory"
    base.mkdir(parents=True)
    if engine_name is not None:
        _stand_in(base / "engine", engine_name)


def _run(home: Path, run_id: str, repo: Path, kit_hash: str) -> None:
    run_dir = home / "runs" / "local" / "repo" / run_id
    run_dir.mkdir(parents=True)
    run = {"schema_version": 1, "run_id": run_id, "repo": repo.name, "repo_key": "local/repo",
           "repo_path": str(repo), "status": "running", "stage": None, "stages": [], "loops": {},
           "workflow": "chore", "attention": None, "kit_hash": kit_hash}
    (run_dir / "run.json").write_text(json.dumps(run))


def _dispatch(argv: list[str], repo: Path, home: Path, capfd, **kw) -> tuple[int, str]:
    code = cli._dispatch(argv, repo, home, **kw)
    return code, capfd.readouterr().out


def test_each_run_is_answered_by_its_own_repos_engine(home, tmp_path, capfd):
    alpha = _repo(tmp_path, "alpha", "engine-alpha")
    beta = _repo(tmp_path, "beta", "engine-beta")
    _snapshot(home, "aaaa", "engine-alpha")
    _snapshot(home, "bbbb", "engine-beta")
    _run(home, "run-alpha", alpha, "aaaa")
    _run(home, "run-beta", beta, "bbbb")

    _, out_a = _dispatch(["status", "run-alpha"], alpha, home, capfd, run_id="run-alpha")
    _, out_b = _dispatch(["status", "run-beta"], beta, home, capfd, run_id="run-beta")

    assert "ENGINE engine-alpha" in out_a
    assert "ENGINE engine-beta" in out_b


def test_a_run_keeps_its_engine_after_the_repo_moves_to_a_new_kit(home, tmp_path, capfd):
    alpha = _repo(tmp_path, "alpha", "engine-alpha")
    _snapshot(home, "aaaa", "engine-alpha")
    _run(home, "run-alpha", alpha, "aaaa")
    # The repo is upgraded: its committed engine changes, and so does the kit a new run would use.
    _stand_in(alpha / "factory" / "engine", "engine-alpha-v2")
    _git("add", "-A", cwd=alpha)
    _git("commit", "-q", "-m", "upgrade", cwd=alpha)

    _, out = _dispatch(["status", "run-alpha"], alpha, home, capfd, run_id="run-alpha")

    assert "ENGINE engine-alpha" in out
    assert "v2" not in out


def test_a_run_whose_snapshot_has_no_engine_starts_nothing_and_says_why(home, tmp_path, capfd):
    alpha = _repo(tmp_path, "alpha", "engine-alpha")
    _snapshot(home, "cccc", None)
    _run(home, "run-old", alpha, "cccc")

    code = cli._engine_passthrough(["status", "run-old", "--json"])
    out = capfd.readouterr().out

    assert code == 2
    assert '"code": "kit.no_engine"' in out
    assert "--installed-engine" in out
    assert "ENGINE" not in out  # no engine printed: nothing was started


def test_installed_engine_runs_the_command_even_when_the_snapshot_has_no_engine(home, tmp_path, capfd, monkeypatch):
    alpha = _repo(tmp_path, "alpha", "engine-alpha")
    _snapshot(home, "cccc", None)
    _run(home, "run-old", alpha, "cccc")
    calls = []
    monkeypatch.setattr(cli, "_engine_argv", lambda argv, repo: calls.append(argv) or [sys.executable, "-c", "print('INSTALLED')"])

    code = cli._engine_passthrough(["status", "run-old", "--installed-engine"])

    assert code == 0
    assert "INSTALLED" in capfd.readouterr().out
    assert "--installed-engine" not in calls[0]  # the engine never sees the launcher flag


def test_abort_runs_on_the_runs_own_engine(home, tmp_path, capfd):
    alpha = _repo(tmp_path, "alpha", "engine-alpha")
    _snapshot(home, "aaaa", "engine-alpha")
    _run(home, "run-alpha", alpha, "aaaa")

    _, out = _dispatch(["abort", "run-alpha"], alpha, home, capfd, run_id="run-alpha")

    assert "ENGINE engine-alpha" in out
    assert "'abort'" in out


def test_a_command_that_creates_a_run_uses_the_repos_own_engine(home, tmp_path, capfd):
    alpha = _repo(tmp_path, "alpha", "engine-alpha")

    _, out = _dispatch(["add", "--title", "x"], alpha, home, capfd)

    assert "ENGINE engine-alpha" in out


def test_a_creating_command_with_no_repo_engine_fails_with_kit_no_engine(home, tmp_path, capfd):
    bare = tmp_path / "bare"
    bare.mkdir()
    _git("init", "-q", cwd=bare)

    with pytest.raises(Exception) as info:
        cli._repo_engine_env(bare, dict(os.environ))

    assert getattr(info.value, "code", None) == "kit.no_engine"


def test_tick_started_engine_runs_the_runs_own_snapshot_engine(home, tmp_path, monkeypatch):
    """spawn_engine (what tick calls) puts the run's snapshot engine on PYTHONPATH, so a child process runs it."""
    from factory_engine import api

    alpha = _repo(tmp_path, "alpha", "engine-alpha")
    _snapshot(home, "aaaa", "engine-alpha")
    _run(home, "run-alpha", alpha, "aaaa")
    marker = tmp_path / "which-engine.txt"
    # The snapshot's engine writes which package answered; the child runs `factory_engine run ...`.
    (home / "kits" / "aaaa" / "factory" / "engine" / "factory_engine" / "__main__.py").write_text(
        f"import factory_engine, pathlib\npathlib.Path({str(marker)!r}).write_text(factory_engine.__file__)\n")

    pid = api.spawn_engine(alpha, "run-alpha")
    assert pid is not None
    import time
    for _ in range(200):
        if marker.exists():
            break
        time.sleep(0.05)

    assert marker.exists(), "the tick-started engine did not run"
    assert str(home / "kits" / "aaaa") in marker.read_text()


def test_tick_spawn_refuses_a_run_whose_snapshot_has_no_engine(home, tmp_path):
    from factory_engine import api
    from factory_engine.errors import FactoryError

    alpha = _repo(tmp_path, "alpha", "engine-alpha")
    _snapshot(home, "cccc", None)
    _run(home, "run-old", alpha, "cccc")

    with pytest.raises(FactoryError) as info:
        api.spawn_engine(alpha, "run-old")

    assert info.value.code == "kit.no_engine"


@pytest.mark.parametrize("command", [["init"], ["upgrade", "0.2.0"], ["doctor"]])
def test_a_kit_command_runs_on_the_installed_engine_even_before_the_repo_has_one(home, tmp_path, capfd, command,
                                                                                  monkeypatch):
    """init, upgrade and doctor manage the kit, so they run before a repo has an engine; they must not need one."""
    monkeypatch.delenv("PYTHONPATH", raising=False)  # a PYTHONPATH from the shell is not what this test is about
    bare = tmp_path / "bare"
    bare.mkdir()
    _git("init", "-q", cwd=bare)

    seen: list[dict] = []

    def fake_run(argv, **kwargs):
        seen.append(kwargs["env"])
        return subprocess.CompletedProcess(argv, 0)

    original = cli.subprocess.run
    cli.subprocess.run = fake_run
    try:
        code = cli._dispatch(command, bare, home)
    finally:
        cli.subprocess.run = original
    assert code == 0
    assert len(seen) == 1 and "PYTHONPATH" not in seen[0]
