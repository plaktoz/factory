"""Module 3, part 2 acceptance criteria: init_repo, upgrade, doctor."""

import subprocess
from pathlib import Path

import pytest

from factory_engine import kit
from factory_engine.errors import FactoryError


@pytest.fixture
def fake_kit(tmp_path, monkeypatch):
    src = tmp_path / "kit-src"
    (src / "workflows").mkdir(parents=True)
    (src / "workflows" / "bug-fix.yaml").write_text("name: bug-fix\n")
    (src / "engine" / "factory_engine").mkdir(parents=True)
    (src / "engine" / "factory_engine" / "x.py").write_text("# the engine: copied\n")
    (src / "engine" / "tests").mkdir()
    (src / "engine" / "tests" / "test_x.py").write_text("# engine tests: not copied\n")
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "z.pyc").write_text("x")
    (src / "AGENTS.md").write_text("rules\n")
    monkeypatch.setattr(kit, "KIT_SOURCE", src)
    return src


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (r / ".gitignore").write_text("node_modules/\n")
    return r


def snapshot_tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file() and ".git/" not in str(p)}


def test_init_creates_the_layout(repo, fake_kit):
    report = kit.init_repo(repo)
    assert (repo / "factory" / "workflows" / "bug-fix.yaml").is_file()
    assert (repo / ".factory" / ".gitignore").read_text() == "*\n!config/\n!config/**\n!.gitignore\n"
    assert (repo / ".factory" / "config" / "factory.yaml").is_file()
    assert (repo / ".factory" / "config" / "merge-policy.yaml").is_file()
    assert (repo / ".factory" / "inbox").is_dir()
    assert repo / "factory" in report.created


def test_init_copies_the_engine_but_not_its_tests_or_caches(repo, fake_kit):
    kit.init_repo(repo)
    assert (repo / "factory" / "engine" / "factory_engine" / "x.py").is_file()
    assert not (repo / "factory" / "engine" / "tests").exists()
    assert not (repo / "factory" / "__pycache__").exists()


def test_init_never_edits_the_root_gitignore(repo, fake_kit):
    before = (repo / ".gitignore").read_bytes()
    kit.init_repo(repo)
    assert (repo / ".gitignore").read_bytes() == before


def test_a_second_init_changes_nothing(repo, fake_kit):
    kit.init_repo(repo)
    first = snapshot_tree(repo)
    again = kit.init_repo(repo)
    assert snapshot_tree(repo) == first
    assert again.created == [] and len(again.unchanged) >= 4


def test_init_keeps_a_config_the_owner_edited(repo, fake_kit):
    kit.init_repo(repo)
    f = repo / ".factory" / "config" / "factory.yaml"
    f.write_text("base_branch: develop\ntracker: file\nharness: claude\n")
    kit.init_repo(repo)
    assert "develop" in f.read_text()


def test_starter_config_validates_against_its_schemas(repo, fake_kit):
    from factory_engine.validate import validate
    from factory_engine.yamlio import load_yaml
    kit.init_repo(repo)
    for name, schema in (("factory.yaml", "factory-config"), ("merge-policy.yaml", "merge-policy")):
        validate(load_yaml((repo / ".factory" / "config" / name).read_text()), schema)


def test_the_inner_gitignore_hides_everything_but_config(repo, fake_kit):
    kit.init_repo(repo)
    (repo / ".factory" / "inbox" / "req.md").write_text("x")
    (repo / ".factory" / "runs").mkdir()
    (repo / ".factory" / "runs" / "r.json").write_text("{}")
    tracked = subprocess.run(["git", "-C", str(repo), "add", "-A", "--dry-run"], capture_output=True, text=True).stdout
    assert ".factory/config/factory.yaml" in tracked
    assert "inbox" not in tracked and "runs" not in tracked


def test_init_refuses_a_missing_folder(tmp_path, fake_kit):
    with pytest.raises(FactoryError) as e:
        kit.init_repo(tmp_path / "nope")
    assert e.value.code == "config.invalid"


def test_upgrade_replaces_the_kit_and_never_touches_config(repo, fake_kit):
    kit.init_repo(repo)
    f = repo / ".factory" / "config" / "factory.yaml"
    f.write_text("base_branch: develop\ntracker: file\nharness: claude\n")
    (repo / "factory" / "stale.txt").write_text("old kit file")
    (fake_kit / "workflows" / "chore.yaml").write_text("name: chore\n")
    report = kit.upgrade(repo, "0.2.0")
    assert (repo / "factory" / "workflows" / "chore.yaml").is_file()
    assert not (repo / "factory" / "stale.txt").exists()
    assert "develop" in f.read_text()
    assert report.config_untouched and report.problems == []


def test_upgrade_reports_a_config_the_new_schema_refuses(repo, fake_kit):
    kit.init_repo(repo)
    (repo / ".factory" / "config" / "factory.yaml").write_text("base_branch: main\ntracker: svn\nharness: claude\n")
    report = kit.upgrade(repo, "0.2.0")
    assert any("factory.yaml" in p for p in report.problems)
    assert report.config_untouched  # reported, not rewritten


def test_upgrade_without_a_kit_says_to_init(tmp_path, fake_kit):
    r = tmp_path / "bare"
    r.mkdir()
    with pytest.raises(FactoryError, match="no factory/ folder"):
        kit.upgrade(r, "0.2.0")


# --- doctor ---

def by_name(results):
    return {r.name: r for r in results}


def test_doctor_finds_git_and_flags_missing_credentials(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    r = by_name(kit.doctor(None))
    assert r["git"].ok
    assert not r["credentials"].ok and "login session is not supported" in r["credentials"].hint


def test_doctor_accepts_a_key_or_a_token_with_a_base_url(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert by_name(kit.doctor(None))["credentials"].ok
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "t")
    assert not by_name(kit.doctor(None))["credentials"].ok  # a token alone is a configuration error
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw")
    assert by_name(kit.doctor(None))["credentials"].ok


def test_doctor_as_scheduler_runs_in_an_empty_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("SECRET_THING", "x")
    results = by_name(kit.doctor(None, as_scheduler=True))
    assert not results["credentials"].ok, "cron has no secrets, so the key in the shell must not count"


def test_doctor_as_scheduler_runs_every_check_the_normal_run_runs(repo, fake_kit, monkeypatch):
    """Acceptance: --as-scheduler runs every check in an empty environment. The same checks are listed, and the
    environment is empty (a key in the shell does not count)."""
    kit.init_repo(repo)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    normal = [r.name for r in kit.doctor(repo)]
    scheduled = by_name(kit.doctor(repo, as_scheduler=True))
    assert list(scheduled) == normal and len(normal) >= 4
    assert not scheduled["credentials"].ok  # cron has no secrets


def test_upgrade_leaves_a_runs_kit_snapshot_and_its_kit_hash_alone(repo, fake_kit, tmp_path):
    """Acceptance: a run created before upgrade keeps using its own kit snapshot."""
    from factory_engine import gitops, state
    from factory_engine.types import Request, Source
    kit.init_repo(repo)
    ident = ["-c", "user.name=t", "-c", "user.email=t@x.invalid", "-C", str(repo)]
    subprocess.run(["git", *ident, "add", "-A"], check=True)
    subprocess.run(["git", *ident, "commit", "-q", "-m", "kit"], check=True)
    home = tmp_path / "home"
    h = gitops.snapshot_kit(repo, "HEAD", home)
    rq = Request("r1", Source("cli", "r1", "t", "b", [], None, []), "sha", "repo", "t", "bug", None, None, [])
    ref = state.init_run(home, repo, "local/repo", "run-1", rq, branch="run-1", worktree=tmp_path / "wt", kit_hash=h)
    before = snapshot_tree(home / "kits" / h)
    (fake_kit / "workflows" / "bug-fix.yaml").write_text("name: bug-fix v2\n")
    kit.upgrade(repo, "2")
    assert (repo / "factory" / "workflows" / "bug-fix.yaml").read_text() == "name: bug-fix v2\n"  # the repo moved on
    assert snapshot_tree(home / "kits" / h) == before                                              # the run did not
    assert state.read_run(ref.run_dir).kit_hash == h


def test_upgrade_after_a_crash_between_the_swap_steps_installs_the_new_kit_and_keeps_the_old_one_until_then(repo, fake_kit):
    """Module 3, Upgrade: a process that dies after moving factory/ aside leaves factory.old/ and no factory/. The next
    upgrade must not say "run factory init first" (init would build a fresh kit and lose the old one's edits); it
    installs the new kit and only then removes factory.old/."""
    kit.init_repo(repo)
    (repo / "factory" / "old.txt").write_text("the old kit")
    real, calls = kit.os.replace, []

    def dies_after_the_move_aside(a, b):
        calls.append(b)
        if len(calls) == 2:           # the second replace puts factory.new/ in place: the process dies before it
            raise KeyboardInterrupt
        return real(a, b)

    kit.os.replace = dies_after_the_move_aside
    try:
        with pytest.raises(KeyboardInterrupt):
            kit.upgrade(repo, "2")
    finally:
        kit.os.replace = real
    assert not (repo / "factory").exists() and (repo / "factory.old" / "old.txt").read_text() == "the old kit"
    report = kit.upgrade(repo, "2")
    assert report.replaced == repo / "factory" and (repo / "factory" / "workflows" / "bug-fix.yaml").is_file()
    assert not (repo / "factory.old").exists() and not (repo / "factory.new").exists()


def test_doctor_in_the_cli_exits_1_when_a_check_fails_and_0_when_all_pass(repo, fake_kit, monkeypatch, capsys):
    """Module 3, doctor: exit 0 when every check passes, 1 when any fails; --no-repo checks the machine only."""
    from factory_engine import api, cli
    monkeypatch.setattr(api, "doctor", lambda r, as_scheduler=False: [kit.CheckResult("a", True, "ok", "")])
    assert cli.main(["doctor", "--no-repo", "--json"]) == 0
    monkeypatch.setattr(api, "doctor", lambda r, as_scheduler=False: [kit.CheckResult("a", True, "ok", ""), kit.CheckResult("b", False, "bad", "fix it")])
    assert cli.main(["doctor", "--no-repo", "--json"]) == 1
    capsys.readouterr()


def test_doctor_reports_a_bad_repo_config(repo, fake_kit):
    kit.init_repo(repo)
    assert by_name(kit.doctor(repo))["repo-config"].ok
    (repo / ".factory" / "config" / "factory.yaml").write_text("base_branch: main\ntracker: github\nharness: codex\n")
    r = by_name(kit.doctor(repo))["repo-config"]
    assert not r.ok and "factory.yaml" in r.detail


def test_doctor_reports_a_repo_with_no_init(tmp_path):
    r = tmp_path / "bare"
    r.mkdir()
    assert not by_name(kit.doctor(r))["repo-config"].ok


def _go_repo_with_no_tools(repo, monkeypatch, tmp_path):
    cfg = repo / ".factory" / "config"
    cfg.mkdir(parents=True)
    (cfg / "factory.yaml").write_text("base_branch: main\ntracker: github\nharness: claude\n")
    (repo / "go.mod").write_text("module x\n")
    monkeypatch.setenv("PATH", str(tmp_path))  # no tools on PATH


def test_the_driver_adds_the_toolchain_checks_to_modules_3s_doctor(repo, fake_kit, monkeypatch, tmp_path):
    """Module 17A: `factory doctor` reports a tool a detected profile needs, before any run. The driver (module 16)
    composes it: module 3 cannot, because 17A depends on 3."""
    from factory_engine import api
    _go_repo_with_no_tools(repo, monkeypatch, tmp_path)
    checks = api.doctor(repo)
    assert any(r.name == "toolchain:go:golangci-lint" and not r.ok for r in checks), checks
    assert [r.name for r in checks if not r.name.startswith("toolchain:") and r.name not in ("skills-lock", "practice-packs")] == [r.name for r in kit.doctor(repo)]


def test_the_driver_adds_module_10s_lock_and_pack_checks(repo, fake_kit, monkeypatch, tmp_path):
    """Module 10: `factory doctor` reports an uninstalled locked skill and a pack over its line limit."""
    from factory_engine import api, skills
    _go_repo_with_no_tools(repo, monkeypatch, tmp_path)
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    by = {r.name: r for r in api.doctor(repo)}
    assert by["skills-lock"].ok and by["practice-packs"].ok
    (repo / "factory").mkdir()
    (repo / "factory" / "skills.lock").write_text("sources: {ex: {repo: /nowhere, ref: abc}}\n")
    kit_root = tmp_path / "pk"
    big = kit_root / "skills" / "own" / "practices" / "java"
    big.mkdir(parents=True)
    (big / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\n" + "line\n" * 200)
    monkeypatch.setattr(skills, "KIT", kit_root)
    by = {r.name: r for r in api.doctor(repo)}
    assert not by["skills-lock"].ok and "not installed" in by["skills-lock"].detail
    assert not by["practice-packs"].ok and "java is" in by["practice-packs"].detail


def test_modules_3_doctor_reports_only_its_own_checks(repo, fake_kit, monkeypatch, tmp_path):
    _go_repo_with_no_tools(repo, monkeypatch, tmp_path)
    assert {r.name for r in kit.doctor(repo)} == {"git", "gh", "credentials", "repo-config"}


# --- a failed upgrade ---

def test_a_failed_copy_leaves_the_old_kit_whole_and_no_scratch_folder(repo, fake_kit, monkeypatch):
    kit.init_repo(repo)
    (repo / "factory" / "stale.txt").write_text("old kit file")
    real, calls = kit.shutil.copytree, []

    def dies_halfway(src, dst, *a, **kw):
        if calls:  # copytree calls itself for each folder: only the outer call is the one that fails
            return real(src, dst, *a, **kw)
        calls.append(dst)
        real(src, dst, *a, **kw)
        (Path(dst) / "half.txt").write_text("partial")
        raise OSError("disk full")

    monkeypatch.setattr(kit.shutil, "copytree", dies_halfway)
    with pytest.raises(FactoryError) as e:
        kit.upgrade(repo, "0.2.0")
    assert e.value.code == "config.invalid" and "disk full" in e.value.message and e.value.hint
    assert (repo / "factory" / "stale.txt").read_text() == "old kit file"
    assert not (repo / "factory" / "half.txt").exists()
    assert sorted(p.name for p in repo.iterdir() if p.name.startswith("factory")) == ["factory"]


def test_upgrade_refuses_to_replace_the_folder_it_copies_from(repo, fake_kit):
    kit.init_repo(repo)
    kit.use_kit_source(repo / "factory")
    before = snapshot_tree(repo / "factory")
    with pytest.raises(FactoryError, match="replace"):
        kit.upgrade(repo, "0.2.0")
    assert snapshot_tree(repo / "factory") == before


def test_a_config_the_new_schema_refuses_is_reported_after_the_kit_is_replaced(repo, fake_kit):
    """The failure path of a bad config: the kit is already replaced and the config untouched, so the fix is to edit
    the config and run upgrade again."""
    kit.init_repo(repo)
    (repo / ".factory" / "config" / "factory.yaml").write_text("base_branch: main\ntracker: svn\nharness: claude\n")
    (fake_kit / "workflows" / "chore.yaml").write_text("name: chore\n")
    report = kit.upgrade(repo, "0.2.0")
    assert report.problems and (repo / "factory" / "workflows" / "chore.yaml").is_file()


def test_a_scratch_folder_left_by_a_dead_process_is_cleared_by_the_next_upgrade(repo, fake_kit):
    kit.init_repo(repo)
    for name in ("factory.new", "factory.old"):
        (repo / name).mkdir()
        (repo / name / "leftover.txt").write_text("from a process that died")
    kit.upgrade(repo, "0.2.0")
    assert sorted(p.name for p in repo.iterdir() if p.name.startswith("factory")) == ["factory"]
    assert (repo / "factory" / "AGENTS.md").is_file()
