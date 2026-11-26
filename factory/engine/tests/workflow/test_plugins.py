"""Module 5 plugins: `insert` joins the chain, and a plugin applies only once `factory plugins enable` has recorded it.

The built-in bug-fix workflow is the base. Its verify stage is followed by review, so an insert after verify has a
stage that waits for it.
"""

import subprocess
from pathlib import Path

import pytest

from factory_engine import skills
from factory_engine.config import Config
from factory_engine.errors import FactoryError
from factory_engine.plugins import disable_plugin, enable_plugin, plugin_status
from factory_engine.workflow import load_workflow

KIT = Path(__file__).resolve().parents[3]  # factory/
CFG = Config(machine={}, repo={})

LINT_EXTRA = """name: lint-extra
version: 0.1.0
applies_to: [bug-fix]
insert:
  after: verify
  stage:
    id: lint-extra
    tasks:
      - {id: lint, cmd: [echo, ok], out: lint.txt}
    join: all
"""


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    skills.use_kit(KIT)
    yield
    skills.use_kit(Path(skills.__file__).resolve().parents[2])


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / ".factory" / "config" / "workflows").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    return r


def add_plugin(repo: Path, text: str = LINT_EXTRA, name: str = "lint-extra") -> Path:
    folder = repo / ".factory" / "config" / "plugins" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.yaml").write_text(text)
    return folder


def stage_ids(wf) -> list[str]:
    return [s.id for s in wf.stages]


def test_an_enabled_plugin_with_after_verify_puts_its_stage_right_after_verify(repo):
    add_plugin(repo)
    enable_plugin(repo, CFG, "lint-extra")
    wf = load_workflow(repo, CFG, "bug-fix")
    ids = stage_ids(wf)
    assert ids[ids.index("verify") + 1] == "lint-extra"


def test_the_inserted_stage_records_its_plugin_as_its_source(repo):
    add_plugin(repo)
    enable_plugin(repo, CFG, "lint-extra")
    wf = load_workflow(repo, CFG, "bug-fix")
    inserted = next(s for s in wf.stages if s.id == "lint-extra")
    assert inserted.source == "plugin:lint-extra"
    assert next(s for s in wf.stages if s.id == "fix").source == "workflow"


def test_loading_a_plugin_leaves_the_workflow_file_byte_for_byte_unchanged(repo):
    add_plugin(repo)
    enable_plugin(repo, CFG, "lint-extra")
    path = KIT / "workflows" / "bug-fix.yaml"
    before = path.read_bytes()
    load_workflow(repo, CFG, "bug-fix")
    assert path.read_bytes() == before


def test_the_stage_that_followed_verify_now_waits_for_the_inserted_stage(repo):
    add_plugin(repo)
    enable_plugin(repo, CFG, "lint-extra")
    wf = load_workflow(repo, CFG, "bug-fix")
    review = next(s for s in wf.stages if s.id == "review")
    assert "lint-extra" in review.needs
    assert next(s for s in wf.stages if s.id == "lint-extra").needs == ["verify"]


def test_a_plugin_that_was_never_enabled_is_not_applied(repo):
    add_plugin(repo)
    wf = load_workflow(repo, CFG, "bug-fix")
    assert "lint-extra" not in stage_ids(wf)


def test_a_disabled_plugin_is_no_longer_applied(repo):
    add_plugin(repo)
    enable_plugin(repo, CFG, "lint-extra")
    disable_plugin(repo, "lint-extra")
    assert "lint-extra" not in stage_ids(load_workflow(repo, CFG, "bug-fix"))


def test_an_insert_that_names_no_stage_is_refused_at_load(repo):
    add_plugin(repo, LINT_EXTRA.replace("after: verify", "after: nowhere"))
    with pytest.raises(FactoryError) as e:
        enable_plugin(repo, CFG, "lint-extra")
    assert e.value.code == "config.invalid" and "nowhere" in e.value.message


# ---- hash, enable and disable: module 5 Safety ----

def test_a_plugin_whose_file_changed_after_enable_is_off_with_a_message_naming_the_file(repo):
    folder = add_plugin(repo)
    enable_plugin(repo, CFG, "lint-extra")
    (folder / "plugin.yaml").write_text(LINT_EXTRA.replace("0.1.0", "0.2.0"))
    wf = load_workflow(repo, CFG, "bug-fix")
    assert "lint-extra" not in stage_ids(wf)
    off = plugin_status(repo, CFG, "lint-extra")
    assert off["state"] == "off" and "plugin.yaml" in off["reason"]


def test_a_changed_file_in_a_plugin_folder_names_that_file_in_the_reason(repo):
    folder = add_plugin(repo)
    (folder / "scan.py").write_text("print(1)\n")
    enable_plugin(repo, CFG, "lint-extra")
    (folder / "scan.py").write_text("print(2)\n")
    assert "scan.py" in plugin_status(repo, CFG, "lint-extra")["reason"]


def test_enable_records_the_hash_outside_the_repo(repo, tmp_path):
    add_plugin(repo)
    enable_plugin(repo, CFG, "lint-extra")
    assert (tmp_path / "home" / "plugin-hashes.json").is_file()
    assert not any(p.name == "plugin-hashes.json" for p in repo.rglob("*"))


def test_an_unreadable_hash_file_turns_every_plugin_off_and_the_summary_says_why(repo, tmp_path):
    add_plugin(repo)
    enable_plugin(repo, CFG, "lint-extra")
    (tmp_path / "home" / "plugin-hashes.json").write_text("{not json")
    wf = load_workflow(repo, CFG, "bug-fix")
    assert "lint-extra" not in stage_ids(wf)
    assert "plugin-hashes.json" in plugin_status(repo, CFG, "lint-extra")["reason"]


def test_disable_turns_a_plugin_off_until_it_is_enabled_again(repo):
    add_plugin(repo)
    enable_plugin(repo, CFG, "lint-extra")
    disable_plugin(repo, "lint-extra")
    assert plugin_status(repo, CFG, "lint-extra")["state"] == "off"
    enable_plugin(repo, CFG, "lint-extra")
    assert "lint-extra" in stage_ids(load_workflow(repo, CFG, "bug-fix"))


# ---- (b) a plugin task with run: is deterministic and loads (module 5 contract, module 9) ----

SCRIPT_TASK = """name: lint-extra
version: 0.1.0
applies_to: [bug-fix]
insert:
  after: verify
  stage:
    id: lint-extra
    tasks:
      - {id: scan, run: {script: scripts/scan.py}, out: scan.json}
"""


def test_a_plugin_script_task_is_parsed_as_a_deterministic_task_with_its_run_spec(repo):
    folder = add_plugin(repo, SCRIPT_TASK)
    (folder / "scripts").mkdir()
    (folder / "scripts" / "scan.py").write_text("print('{}')\n")
    enable_plugin(repo, CFG, "lint-extra")
    wf = load_workflow(repo, CFG, "bug-fix")
    task = next(t for s in wf.stages if s.id == "lint-extra" for t in s.tasks)
    assert task.run is not None and task.run.script == "scripts/scan.py"
    assert task.skill is None and task.cmd is None
    assert task.retries == 0  # a deterministic task gets no retries by default (module 5)


def test_a_plugin_python_task_names_its_function_and_is_deterministic(repo):
    text = SCRIPT_TASK.replace("run: {script: scripts/scan.py}", "run: {python: scan:check, args: [--strict]}")
    add_plugin(repo, text)
    enable_plugin(repo, CFG, "lint-extra")
    wf = load_workflow(repo, CFG, "bug-fix")
    task = next(t for s in wf.stages if s.id == "lint-extra" for t in s.tasks)
    assert task.run.python == "scan:check" and task.run.args == ["--strict"]


def test_a_plugin_task_with_both_run_and_cmd_is_refused(repo):
    text = SCRIPT_TASK.replace("run: {script: scripts/scan.py}", "run: {script: scripts/scan.py}, cmd: [make]")
    add_plugin(repo, text)
    with pytest.raises(FactoryError) as e:
        enable_plugin(repo, CFG, "lint-extra")
    assert e.value.code == "config.invalid"


# ---- os: and requires.skills: module 5 manifest keys and Safety (c) ----

SH_HOOK = """name: notify
version: 0.1.0
applies_to: [bug-fix]
os: [linux]
insert:
  after: verify
  stage:
    id: notify
hooks:
  - {on: [run_done], run: {script: hooks/notify.sh}}
"""


def test_a_sh_script_on_a_system_not_in_os_fails_at_enable(repo, monkeypatch):
    from factory_engine import plugins

    monkeypatch.setattr(plugins, "current_system", lambda: "macos")
    folder = add_plugin(repo, SH_HOOK, name="notify")
    (folder / "hooks").mkdir()
    (folder / "hooks" / "notify.sh").write_text("echo hi\n")
    with pytest.raises(FactoryError) as e:
        enable_plugin(repo, CFG, "notify")
    assert e.value.code == "config.invalid"
    assert "notify.sh" in e.value.message and "macos" in e.value.message


def test_a_sh_script_on_an_unlisted_system_fails_the_workflow_at_load(repo, monkeypatch):
    from factory_engine import plugins

    folder = add_plugin(repo, SH_HOOK, name="notify")
    (folder / "hooks").mkdir()
    (folder / "hooks" / "notify.sh").write_text("echo hi\n")
    monkeypatch.setattr(plugins, "current_system", lambda: "linux")
    enable_plugin(repo, CFG, "notify")
    monkeypatch.setattr(plugins, "current_system", lambda: "macos")
    with pytest.raises(FactoryError) as e:
        load_workflow(repo, CFG, "bug-fix")
    assert e.value.code == "config.invalid" and "notify.sh" in e.value.message


@pytest.mark.parametrize("content", ["[1, 2]", "42", '"text"'])
def test_a_hash_file_that_is_not_a_mapping_turns_every_plugin_off_with_the_reason(repo, tmp_path, content):
    add_plugin(repo)
    enable_plugin(repo, CFG, "lint-extra")
    (tmp_path / "home" / "plugin-hashes.json").write_text(content)
    assert "lint-extra" not in stage_ids(load_workflow(repo, CFG, "bug-fix"))
    assert "plugin-hashes.json" in plugin_status(repo, CFG, "lint-extra")["reason"]


def test_enable_on_an_unreadable_hash_file_is_a_config_error_that_names_the_file(repo, tmp_path):
    add_plugin(repo)
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    (tmp_path / "home" / "plugin-hashes.json").write_text("{not json")
    with pytest.raises(FactoryError) as e:
        enable_plugin(repo, CFG, "lint-extra")
    assert e.value.code == "config.invalid" and "plugin-hashes.json" in e.value.message


def test_a_sh_script_on_a_listed_system_is_accepted(repo, monkeypatch):
    from factory_engine import plugins

    monkeypatch.setattr(plugins, "current_system", lambda: "linux")
    folder = add_plugin(repo, SH_HOOK, name="notify")
    (folder / "hooks").mkdir()
    (folder / "hooks" / "notify.sh").write_text("echo hi\n")
    enable_plugin(repo, CFG, "notify")


def test_a_plugin_that_requires_a_skill_missing_from_the_lock_refuses_to_enable(repo):
    text = LINT_EXTRA.replace("applies_to: [bug-fix]", "requires: {skills: [impeccable]}\napplies_to: [bug-fix]")
    add_plugin(repo, text)
    with pytest.raises(FactoryError) as e:
        enable_plugin(repo, CFG, "lint-extra")
    assert e.value.code == "config.invalid" and "impeccable" in e.value.message


def test_a_run_refuses_to_start_when_a_recorded_plugin_requires_a_skill_the_lock_lacks(repo, tmp_path):
    from factory_engine import plugins, state

    text = LINT_EXTRA.replace("applies_to: [bug-fix]", "requires: {skills: [impeccable]}\napplies_to: [bug-fix]")
    folder = add_plugin(repo, text)
    plugins._write_hashes(tmp_path / "home", state.repo_key(repo, CFG), {"lint-extra": plugins._file_hashes(folder)})
    with pytest.raises(FactoryError) as e:
        load_workflow(repo, CFG, "bug-fix")
    assert e.value.code == "config.invalid" and "impeccable" in e.value.message
