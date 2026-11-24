"""`factory init --github` records the repo in the machine config, and `tick --all-repos` syncs registered repos (Appendix A, step 5)."""

import shutil
import subprocess

import pytest
import yaml

from factory_engine.errors import FactoryError
from factory_launcher import cli, repos


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(h))
    return h


def _repo(tmp_path, name="proj"):
    r = tmp_path / name
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    return r.resolve()


def test_register_adds_the_repo_once(home, tmp_path):
    r = _repo(tmp_path)
    repos.register(home, r)
    repos.register(home, r)
    assert repos.registered(home) == [r]


def test_register_keeps_the_other_machine_settings_and_comments(home, tmp_path):
    (home / "config.yaml").write_text("# Machine settings.\nrepos: []\ntick: {every_minutes: 10, stale_after_ticks: 3}\n")
    repos.register(home, _repo(tmp_path))
    text = (home / "config.yaml").read_text()
    assert "# Machine settings." in text
    assert yaml.safe_load(text)["tick"] == {"every_minutes": 10, "stale_after_ticks": 3}


def test_register_creates_the_file_when_it_is_missing(home, tmp_path):
    r = _repo(tmp_path)
    repos.register(home, r)
    assert yaml.safe_load((home / "config.yaml").read_text())["repos"] == [str(r)]


def test_a_machine_file_that_is_not_a_mapping_is_left_alone(home, tmp_path):
    (home / "config.yaml").write_text("- not\n- a mapping\n")
    with pytest.raises(FactoryError):
        repos.register(home, _repo(tmp_path))
    assert (home / "config.yaml").read_text() == "- not\n- a mapping\n"


def test_all_repos_includes_registered_repos_with_no_run(home, tmp_path):
    r = _repo(tmp_path)
    repos.register(home, r)
    args = cli._parser().parse_args(["tick", "--all-repos"])
    assert cli._tick_repos(args, home) == [r]


def test_all_repos_skips_a_registered_folder_that_is_gone(home, tmp_path):
    r = _repo(tmp_path)
    repos.register(home, r)
    shutil.rmtree(r)
    args = cli._parser().parse_args(["tick", "--all-repos"])
    assert cli._tick_repos(args, home) == []


def test_init_github_registers_the_repo_after_the_engine_succeeds(home, tmp_path, monkeypatch):
    r = _repo(tmp_path)
    monkeypatch.setattr(cli, "_dispatch_engine", lambda *a, **k: 0)
    assert cli.main(["init", "--github", "--repo", str(r)]) == 0
    assert repos.registered(home) == [r]


def test_init_without_github_registers_nothing(home, tmp_path, monkeypatch):
    r = _repo(tmp_path)
    monkeypatch.setattr(cli, "_dispatch_engine", lambda *a, **k: 0)
    assert cli.main(["init", "--repo", str(r)]) == 0
    assert repos.registered(home) == []


def test_a_failed_init_registers_nothing(home, tmp_path, monkeypatch):
    r = _repo(tmp_path)
    monkeypatch.setattr(cli, "_dispatch_engine", lambda *a, **k: 1)
    assert cli.main(["init", "--github", "--repo", str(r)]) == 1
    assert repos.registered(home) == []
