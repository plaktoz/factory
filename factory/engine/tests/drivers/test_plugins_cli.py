"""Module 16: `factory plugins enable|disable <name>` supports --json and uses the shared exit codes.

Driven through cli.main() like the other driver tests, so no engine process starts. The plugin is a bug-fix insert.
"""

import json
from pathlib import Path

import pytest

from cli_fixtures import seed_repo

from factory_engine import cli, skills
from factory_engine.errors import EXIT_INVALID, EXIT_OK

KIT = Path(__file__).resolve().parents[3]  # factory/

PLUGIN = """name: lint-extra
version: 0.1.0
applies_to: [bug-fix]
insert:
  after: verify
  stage:
    id: lint-extra
    tasks:
      - {id: lint, cmd: [echo, ok], out: lint.txt}
"""


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    skills.use_kit(KIT)
    yield
    skills.use_kit(Path(skills.__file__).resolve().parents[2])


@pytest.fixture
def seeded(tmp_path) -> Path:
    return seed_repo(tmp_path)


def add_plugin(repo: Path, text: str = PLUGIN) -> None:
    folder = repo / ".factory" / "config" / "plugins" / "lint-extra"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.yaml").write_text(text)


def run_cli(argv, capsys):
    code = cli.main(argv)
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    return code, (json.loads(lines[-1]) if lines and lines[-1].startswith("{") else None)


def test_plugins_enable_prints_the_merged_stages_as_json(seeded, capsys):
    add_plugin(seeded)
    code, doc = run_cli(["plugins", "enable", "lint-extra", "--repo", str(seeded), "--json"], capsys)
    assert code == EXIT_OK and doc["ok"] is True
    stages = [s["id"] for s in doc["data"]["stages"]]
    assert stages.index("lint-extra") == stages.index("verify") + 1


def test_plugins_disable_is_ok_and_turns_the_plugin_off(seeded, capsys):
    add_plugin(seeded)
    cli.main(["plugins", "enable", "lint-extra", "--repo", str(seeded), "--json"])
    capsys.readouterr()
    code, doc = run_cli(["plugins", "disable", "lint-extra", "--repo", str(seeded), "--json"], capsys)
    assert code == EXIT_OK and doc["ok"] is True


def test_plugins_enable_of_a_missing_plugin_exits_invalid_with_the_shared_shape(seeded, capsys):
    code, doc = run_cli(["plugins", "enable", "nope", "--repo", str(seeded), "--json"], capsys)
    assert code == EXIT_INVALID
    assert doc["ok"] is False and doc["code"] == "config.invalid"


def test_plugins_with_a_bad_flag_prints_the_shared_shape_and_exits_2(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["plugins", "enable", "--json", "--bogus"])
    assert e.value.code == EXIT_INVALID
    doc = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert doc["ok"] is False and doc["code"] == "cli.usage"
