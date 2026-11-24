"""Module 3, part 1 acceptance criteria: config, interpolation, precedence, YAML, schemas, paths, masking."""

import pytest

from factory_engine import interpolate, paths, redact
from factory_engine.errors import FactoryError
from factory_engine.loadcfg import load_config, resolve_harness
from factory_engine.repo_rules import check_cleanup_check, refuse_literal_env
from factory_engine.validate import validate
from factory_engine.yamlio import load_yaml


# --- ${VAR}, ${VAR:-default}, ${VAR:?message} ---

def test_plain_reference_resolves():
    assert interpolate.resolve("key=${K}", {"K": "v"}) == "key=v"


def test_default_used_when_unset_or_empty():
    assert interpolate.resolve("${K:-fallback}", {}) == "fallback"
    assert interpolate.resolve("${K:-fallback}", {"K": ""}) == "fallback"
    assert interpolate.resolve("${K:-fallback}", {"K": "set"}) == "set"


def test_required_unset_fails_with_the_message():
    with pytest.raises(FactoryError) as e:
        interpolate.resolve("${OPENAI_API_KEY:?set OPENAI_API_KEY or run codex login}", {}, where="x")
    assert e.value.code == "config.invalid"
    assert "set OPENAI_API_KEY or run codex login" in e.value.message


def test_plain_unset_reference_fails():
    with pytest.raises(FactoryError, match="K is not set"):
        interpolate.resolve("${K}", {})


def test_unknown_form_is_refused_not_passed_through():
    with pytest.raises(FactoryError, match="not a form the factory knows"):
        interpolate.resolve("${K/bad}", {})


def test_is_reference_only_for_a_whole_reference():
    assert interpolate.is_reference("${ANTHROPIC_API_KEY}")
    assert interpolate.is_reference("${K:-x}")
    assert not interpolate.is_reference("sk-abc123")
    assert not interpolate.is_reference("prefix-${K}")


# --- literal secrets under env in the repo file ---

def test_literal_env_value_in_repo_config_is_refused():
    with pytest.raises(FactoryError) as e:
        refuse_literal_env({"ANTHROPIC_API_KEY": "sk-literal"}, file=".factory/config/factory.yaml")
    assert e.value.code == "config.invalid" and "literal" in e.value.message


def test_reference_under_env_is_allowed():
    refuse_literal_env({"ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"}, file="f")


# --- YAML: one loader, true and false only as booleans ---

def test_spec_examples_keep_off_and_on_as_strings():
    doc = load_yaml("helpers: {mode: off}\nhooks:\n  - on: [pr_opened]\nflag: true\n")
    assert doc["helpers"]["mode"] == "off"
    assert doc["hooks"][0]["on"] == ["pr_opened"]
    assert doc["flag"] is True


def test_yaml_syntax_error_names_the_line():
    with pytest.raises(FactoryError) as e:
        load_yaml("a: [1,\n", file="factory.yaml")
    assert e.value.code == "config.invalid" and "factory.yaml" in e.value.message


# --- schemas ---

def test_factory_config_schema_refuses_an_unknown_key_with_the_path():
    with pytest.raises(FactoryError) as e:
        validate({"base_branch": "main", "tracker": "github", "harness": "claude", "nope": 1},
                 "factory-config", file="factory.yaml")
    assert e.value.code == "config.invalid" and "factory.yaml" in e.value.message


def test_merge_policy_refuses_a_bad_default():
    with pytest.raises(FactoryError):
        validate({"default": "auto", "auto": {"workflows": [], "type_source": [], "require": {
            "gates": "all_passed", "ci": "green", "max_files": 1, "max_lines": 1}}, "never_auto_if": {}},
            "merge-policy")


def test_missing_schema_is_config_invalid():
    with pytest.raises(FactoryError, match="no schema named"):
        validate({}, "does-not-exist")


# --- cleanup_check is a list ---

def test_cleanup_check_must_be_a_list_of_strings():
    assert check_cleanup_check(["scripts/compare-worktree"], file="f") == ["scripts/compare-worktree"]
    assert check_cleanup_check(None, file="f") is None
    for bad in ("scripts/compare-worktree", [1], [], {"a": 1}):
        with pytest.raises(FactoryError) as e:
            check_cleanup_check(bad, file="f")
        assert e.value.code == "config.invalid"


# --- load_config ---

def write_home(tmp_path, machine_yaml):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(machine_yaml)
    return home


def repo_with(tmp_path, factory_yaml):
    repo = tmp_path / "repo"
    (repo / ".factory" / "config").mkdir(parents=True)
    (repo / ".factory" / "config" / "factory.yaml").write_text(factory_yaml)
    return repo


BASE_REPO = "base_branch: main\ntracker: github\nharness: claude\n"


def test_load_config_none_has_machine_only(tmp_path):
    home = write_home(tmp_path, "max_workers: 3\n")
    cfg = load_config(None, env={"FACTORY_HOME": str(home)})
    assert cfg.repo is None and cfg.machine["max_workers"] == 3


def test_load_config_repo_sets_both_parts(tmp_path):
    home = write_home(tmp_path, "max_workers: 3\n")
    repo = repo_with(tmp_path, BASE_REPO + "concurrency: 2\n")
    cfg = load_config(repo, env={"FACTORY_HOME": str(home)})
    assert cfg.machine["max_workers"] == 3
    assert cfg.repo["base_branch"] == "main" and cfg.repo["concurrency"] == 2
    assert cfg.repo["infra_wait_hours"] == 6  # default


def test_a_missing_machine_file_and_a_missing_repo_file_load_with_the_defaults(tmp_path):
    """Module 3, Missing files: no ~/.factory/config.yaml is the defaults, and a repo with no factory.yaml loads with
    only the repo defaults (doctor, not load_config, reports the missing file)."""
    home = tmp_path / "empty-home"
    home.mkdir()
    repo = tmp_path / "bare"
    repo.mkdir()
    cfg = load_config(repo, env={"FACTORY_HOME": str(home)})
    assert cfg.machine == {"max_workers": 6}
    assert cfg.repo == {"concurrency": 4, "infra_wait_hours": 6, "serialize_overlapping_runs": False}


def test_factory_worktree_root_replaces_the_machine_worktree_root(tmp_path):
    home = write_home(tmp_path, "worktree_root: /from/the/file\n")
    cfg = load_config(None, env={"FACTORY_HOME": str(home), "FACTORY_WORKTREE_ROOT": "/from/the/env"})
    assert cfg.machine["worktree_root"] == "/from/the/env"
    assert load_config(None, env={"FACTORY_HOME": str(home)}).machine["worktree_root"] == "/from/the/file"


def test_load_config_refuses_a_bad_repo_file(tmp_path):
    home = write_home(tmp_path, "")
    repo = repo_with(tmp_path, BASE_REPO + "cleanup_check: scripts/x\n")
    with pytest.raises(FactoryError) as e:
        load_config(repo, env={"FACTORY_HOME": str(home)})
    assert e.value.code == "config.invalid" and "cleanup_check" in e.value.message


def test_repo_without_cleanup_check_or_model_loads_and_resolves_no_model(tmp_path):
    home = write_home(tmp_path, "harnesses:\n  claude:\n    command: claude\n    args: [--output-format, json]\n")
    repo = repo_with(tmp_path, BASE_REPO)
    cfg = load_config(repo, env={"FACTORY_HOME": str(home)})
    assert cfg.repo.get("cleanup_check") is None
    hc = resolve_harness(cfg, "claude", env={})
    assert hc.model is None and hc.command == "claude"


def test_resolve_harness_model_precedence(tmp_path):
    home = write_home(tmp_path, "harnesses:\n  claude:\n    command: claude\n    model: m-harness\n")
    cfg = load_config(None, env={"FACTORY_HOME": str(home)})
    assert resolve_harness(cfg, "claude", env={}).model == "m-harness"
    assert resolve_harness(cfg, "claude", env={}, stage_model="m-stage").model == "m-stage"
    assert resolve_harness(cfg, "claude", env={}, stage_model="m-stage", task_model="m-task").model == "m-task"


def test_resolve_harness_resolves_env_references_at_call_time(tmp_path):
    home = write_home(tmp_path, "harnesses:\n  claude:\n    command: claude\n    env:\n      ANTHROPIC_BASE_URL: ${ANTHROPIC_BASE_URL:?set the gateway URL}\n")
    cfg = load_config(None, env={"FACTORY_HOME": str(home)})
    with pytest.raises(FactoryError, match="set the gateway URL"):
        resolve_harness(cfg, "claude", env={})
    assert resolve_harness(cfg, "claude", env={"ANTHROPIC_BASE_URL": "https://gw"}).env == {"ANTHROPIC_BASE_URL": "https://gw"}


def test_codex_harness_resolves(tmp_path):
    home = write_home(tmp_path, "harnesses:\n  codex:\n    command: codex\n    model: gpt-5\n"
                                "    env:\n      OPENAI_API_KEY: ${OPENAI_API_KEY}\n")
    cfg = load_config(None, env={"FACTORY_HOME": str(home)})
    h = resolve_harness(cfg, "codex", env={"OPENAI_API_KEY": "k"})
    assert (h.command, h.model, h.env) == ("codex", "gpt-5", {"OPENAI_API_KEY": "k"})


def test_unknown_harness_fails_fast_naming_the_accepted_ones(tmp_path):
    home = write_home(tmp_path, "harnesses:\n  gemini:\n    command: gemini\n")
    cfg = load_config(None, env={"FACTORY_HOME": str(home)})
    with pytest.raises(FactoryError) as e:
        resolve_harness(cfg, "gemini", env={})
    assert e.value.code == "config.invalid" and "claude" in e.value.message and "codex" in e.value.message


# --- worktree_path ---

def test_worktree_path_renders_the_example_in_module_3(tmp_path):
    from pathlib import Path
    p = paths.render("{root}/{repo}/{run_id}", root=Path("/home/me/dev/worktree"), repo="report",
                     owner="acme", run_id="new-color-q1w2e", task=None)
    assert str(p) == "/home/me/dev/worktree/report/new-color-q1w2e"


def test_task_worktree_gets_the_double_dash_suffix(tmp_path):
    from pathlib import Path
    p = paths.render("{root}/{repo}/{run_id}", root=Path("/w"), repo="report", owner="a",
                     run_id="new-color-q1w2e", task="backend")
    assert str(p) == "/w/report/new-color-q1w2e--backend"


def test_worktree_inside_the_repo_is_refused(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(FactoryError, match="inside the repo"):
        paths.check_outside_repo(repo / "wt", repo)


def test_worktree_under_dot_factory_worktrees_is_allowed(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".factory" / "worktrees").mkdir(parents=True)
    paths.check_outside_repo(repo / ".factory" / "worktrees" / "r1", repo)


def test_existing_worktree_path_is_refused(tmp_path):
    (tmp_path / "exists").mkdir()
    with pytest.raises(FactoryError, match="already exists"):
        paths.check_not_existing(tmp_path / "exists")


def test_unknown_placeholder_is_refused(tmp_path):
    from pathlib import Path
    with pytest.raises(FactoryError, match="unknown placeholder"):
        paths.render("{root}/{nope}", root=Path("/w"), repo="r", owner="o", run_id="x", task=None)


# --- mask ---

def test_mask_hides_every_secret_and_longest_first():
    assert redact.mask("token=abc123 and abc", ["abc123", "abc"]) == "token=*** and ***"


def test_mask_ignores_empty_secrets():
    assert redact.mask("plain", ["", None] if False else [""]) == "plain"


# --- machine file: a literal secret is allowed, but warned about when other users can read it (module 3, module 9) ---

def _machine_with_literal_env(tmp_path, mode, value="sk-literal"):
    home = write_home(tmp_path, "harnesses:\n  claude:\n    command: claude\n    env:\n"
                                f"      ANTHROPIC_API_KEY: {value}\n")
    (home / "config.yaml").chmod(mode)
    return home


def test_a_machine_file_with_a_literal_env_value_readable_by_others_warns(tmp_path):
    home = _machine_with_literal_env(tmp_path, 0o644)
    with pytest.warns(UserWarning, match="readable by other users") as w:
        load_config(None, env={"FACTORY_HOME": str(home)})
    assert str(home / "config.yaml") in str(w[0].message)


def test_a_machine_file_readable_only_by_its_owner_does_not_warn(tmp_path):
    import warnings
    home = _machine_with_literal_env(tmp_path, 0o600)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        load_config(None, env={"FACTORY_HOME": str(home)})


def test_a_machine_file_with_no_literal_env_value_does_not_warn_even_when_open(tmp_path):
    import warnings
    home = _machine_with_literal_env(tmp_path, 0o644, value="${ANTHROPIC_API_KEY}")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        load_config(None, env={"FACTORY_HOME": str(home)})


# --- merge-policy.yaml is checked against its schema at load, with the file and the fix (module 3) ---

BAD_MERGE_POLICY = ("default: auto\nauto:\n  workflows: []\n  type_source: []\n  require:\n    gates: all_passed\n"
                    "    ci: green\n    max_files: 1\n    max_lines: 1\nnever_auto_if: {}\n")


def test_load_config_refuses_a_bad_merge_policy_naming_the_file_and_the_fix(tmp_path):
    home = write_home(tmp_path, "")
    repo = repo_with(tmp_path, BASE_REPO)
    (repo / ".factory" / "config" / "merge-policy.yaml").write_text(BAD_MERGE_POLICY)
    with pytest.raises(FactoryError) as e:
        load_config(repo, env={"FACTORY_HOME": str(home)})
    assert e.value.code == "config.invalid"
    assert "merge-policy.yaml" in e.value.message and "default" in e.value.message
    assert "merge-policy.schema.json" in e.value.hint


def test_load_config_accepts_a_valid_merge_policy(tmp_path):
    home = write_home(tmp_path, "")
    repo = repo_with(tmp_path, BASE_REPO)
    (repo / ".factory" / "config" / "merge-policy.yaml").write_text(
        "default: human\nauto:\n  workflows: []\n  type_source: [explicit]\n  require:\n    gates: all_passed\n"
        "    ci: green\n    max_files: 10\n    max_lines: 300\nnever_auto_if: {}\n")
    assert load_config(repo, env={"FACTORY_HOME": str(home)}).repo["base_branch"] == "main"
