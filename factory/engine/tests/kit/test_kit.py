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
    (src / "engine").mkdir()
    (src / "engine" / "x.py").write_text("# never copied\n")
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


def test_init_does_not_copy_the_engine_or_caches(repo, fake_kit):
    kit.init_repo(repo)
    assert not (repo / "factory" / "engine").exists()
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


def test_doctor_reports_a_missing_toolchain_tool_for_a_repo(repo, fake_kit, monkeypatch, tmp_path):
    """Module 17A: `factory doctor` reports a tool a detected profile needs, before any run, through the same doctor
    the CLI calls. The repo needs a valid factory.yaml (the profile lookup reads its config) and a go.mod."""
    from factory_engine import kit
    cfg = repo / ".factory" / "config"
    cfg.mkdir(parents=True)
    (cfg / "factory.yaml").write_text("base_branch: main\ntracker: github\nharness: claude\n")
    (repo / "go.mod").write_text("module x\n")
    monkeypatch.setenv("PATH", str(tmp_path))  # no tools on PATH
    tool_checks = [r for r in kit.doctor(repo) if r.name.startswith("toolchain:")]
    assert any(r.name == "toolchain:go:golangci-lint" and not r.ok for r in tool_checks), tool_checks
