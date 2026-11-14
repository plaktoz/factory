"""Module 10 acceptance criteria. Upstream is a local fixture repo (module 10: 'a local fixture repo standing in')."""

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from factory_engine import shims, skills
from factory_engine.config import Config
from factory_engine.errors import FactoryError
from factory_engine.yamlio import load_yaml

KIT = Path(__file__).resolve().parents[3]  # factory/
CFG = Config(machine={}, repo={})
STAGES = ["classify", "reproduce", "root-cause", "propose", "architect", "implement", "fix",
          "review-standards", "review-spec", "scope", "gather", "synthesize", "critique"]


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@x.invalid", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    skills.use_kit(KIT)
    yield
    skills.use_kit(Path(skills.__file__).resolve().parents[2])


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / ".factory" / "config" / "overrides" / "skills").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    git(r, "commit", "-q", "--allow-empty", "-m", "i")
    return r


def make_skill(root: Path, name: str, text: str = "x") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {text}\n---\n{text}\n")
    return d


# ---- resolution order ----

def test_resolution_order_is_override_then_locked_then_own(repo, tmp_path):
    # own only
    assert skills.resolve_skill("fix", repo, CFG).source == "own"
    # a locked skill beats own
    cache = tmp_path / "home" / "skills-cache" / "example" / "fix"
    make_skill(cache.parent, "fix")
    (repo / "factory").mkdir()
    (repo / "factory" / "skills.lock").write_text("sources: {example: {repo: x, ref: r}}\nallow: {example: [fix]}\ndeny: {}\n")
    assert skills.resolve_skill("fix", repo, CFG).source == "locked"
    # an override beats both
    make_skill(repo / ".factory" / "config" / "overrides" / "skills", "fix")
    assert skills.resolve_skill("fix", repo, CFG).source == "override"


def test_a_denied_locked_skill_is_not_used(repo, tmp_path):
    make_skill(tmp_path / "home" / "skills-cache" / "example", "fix")
    (repo / "factory").mkdir()
    (repo / "factory" / "skills.lock").write_text("sources: {example: {repo: x, ref: r}}\nallow: {example: [fix]}\ndeny: {example: [fix]}\n")
    assert skills.resolve_skill("fix", repo, CFG).source == "own"


def test_an_unknown_skill_fails_with_skills_unknown(repo):
    with pytest.raises(FactoryError) as e:
        skills.resolve_skill("no-such-skill", repo, CFG)
    assert e.value.code == "skills.unknown" and e.value.kind == "fail_fast"


# ---- every stage resolves to an own skill with an empty lock ----

def test_the_stage_map_names_every_stage_the_spec_lists():
    m = load_yaml((KIT / "stages.map.yaml").read_text())
    assert sorted(m) == sorted(STAGES)
    assert all(v["skill"] == f"own:{k}" for k, v in m.items())


@pytest.mark.parametrize("stage", STAGES)
def test_with_an_empty_lock_every_stage_resolves_to_an_own_skill(stage, repo):
    assert load_yaml((KIT / "skills.lock").read_text()) == {"sources": {}, "allow": {}, "deny": {}}
    ref = skills.resolve_skill(stage, repo, CFG)
    assert ref.source == "own" and (ref.path / "SKILL.md").is_file()


# ---- own skills ask no question (static check; the run against FakeWorkerAdapter is wave 2, module 9) ----

QUESTION_WORDS = re.compile(r"\b(ask the user|ask the human|ask a question|wait for (the )?(user|human)|confirm with)\b", re.I)


@pytest.mark.parametrize("stage", STAGES)
def test_each_own_skill_has_front_matter_and_the_headless_rules_and_asks_nothing(stage):
    text = (KIT / "skills" / "own" / stage / "SKILL.md").read_text()
    front = yaml.safe_load(text.split("---")[1])
    assert front["name"] == f"factory-{stage}" and front["description"]
    assert "Never ask a question" in text and "Never commit, push, merge or touch an issue" in text
    # the only place a skill may mention asking is the rule that forbids it
    body = text.replace("Never ask a question.", "")
    assert not QUESTION_WORDS.search(body), f"{stage} tells the worker to ask someone"


def test_the_classify_skill_names_the_fields_of_the_triage_schema():
    import json
    schema = json.loads((KIT / "schemas" / "triage.schema.json").read_text())
    text = (KIT / "skills" / "own" / "classify" / "SKILL.md").read_text()
    for field in schema["required"]:
        assert field in text, f"classify does not mention the triage field {field}"


def test_the_architect_skill_names_every_required_packet_field():
    import json
    schema = json.loads((KIT / "schemas" / "packet.schema.json").read_text())
    item = schema["properties"]["decisions"]["items"]
    text = (KIT / "skills" / "own" / "architect" / "SKILL.md").read_text()
    for field in item["required"]:
        assert field in text, f"architect does not mention the packet field {field}"


# ---- install and verify the lock ----

@pytest.fixture
def upstream(tmp_path):
    u = tmp_path / "upstream"
    u.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(u)], check=True)
    make_skill(u, "wanted", "the one we allow")
    make_skill(u, "denied", "must never be installed")
    make_skill(u, "unlisted", "not on the allowlist")
    git(u, "add", "-A")
    git(u, "commit", "-q", "-m", "v1")
    ref = subprocess.run(["git", "-C", str(u), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return u, ref


def write_lock(repo, upstream_path, ref, allow=("wanted",), deny=("denied",)):
    (repo / "factory").mkdir(exist_ok=True)
    (repo / "factory" / "skills.lock").write_text(yaml.safe_dump({"sources": {"ex": {"repo": str(upstream_path), "ref": ref}},
                                                                  "allow": {"ex": list(allow)}, "deny": {"ex": list(deny)}}))


def test_only_allowed_skills_are_fetched_and_denied_ones_are_never_installed(repo, upstream, tmp_path):
    u, ref = upstream
    write_lock(repo, u, ref, allow=("wanted", "denied"), deny=("denied",))
    report = skills.install_locked(repo, CFG)
    cache = tmp_path / "home" / "skills-cache" / "ex"
    assert (cache / "wanted" / "SKILL.md").is_file()
    assert not (cache / "denied").exists()      # denied even though allowed
    assert not (cache / "unlisted").exists()    # never on the allowlist
    assert report.installed == ["ex/wanted"] and report.problems == []


def test_an_empty_allowlist_fetches_nothing(repo, upstream, tmp_path):
    u, ref = upstream
    write_lock(repo, u, ref, allow=(), deny=())
    report = skills.install_locked(repo, CFG)
    assert report.installed == [] and not (tmp_path / "home" / "skills-cache" / "_clones" / "ex").exists()


def test_verify_lock_is_clean_when_the_pinned_ref_is_installed(repo, upstream):
    u, ref = upstream
    write_lock(repo, u, ref)
    skills.install_locked(repo, CFG)
    assert skills.verify_lock(repo) == []


def test_a_changed_upstream_ref_is_reported_by_verify_lock(repo, upstream):
    u, ref = upstream
    write_lock(repo, u, ref)
    skills.install_locked(repo, CFG)
    make_skill(u, "wanted", "changed upstream")
    git(u, "add", "-A"); git(u, "commit", "-q", "-m", "v2")
    new_ref = subprocess.run(["git", "-C", str(u), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    write_lock(repo, u, new_ref)  # the lock now pins the new commit, but the clone is still on the old one
    problems = skills.verify_lock(repo)
    assert problems and "pins" in problems[0].message


def test_verify_lock_reports_a_source_that_was_never_installed(repo, upstream):
    u, ref = upstream
    write_lock(repo, u, ref)
    problems = skills.verify_lock(repo)
    assert problems and "not installed" in problems[0].message


# ---- shims ----

@pytest.fixture
def worktree(repo, tmp_path):
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "run-1", str(wt))
    return wt


def porcelain(wt):
    return subprocess.run(["git", "-C", str(wt), "status", "--porcelain"], capture_output=True, text=True).stdout


def test_shims_appear_in_a_new_worktree_and_never_show_in_git_status(repo, worktree):
    refs = [skills.resolve_skill(s, repo, CFG) for s in ("fix", "classify")]
    made = shims.generate_shims(worktree, ["claude"], refs)
    assert [p.name for p in made] == ["factory-fix", "factory-classify"]
    assert (worktree / ".claude" / "skills" / "factory-fix" / "SKILL.md").is_file()
    assert porcelain(worktree) == ""  # hidden by the two exclude patterns


def test_the_exclude_patterns_are_written_once_per_repo(repo, worktree, tmp_path):
    ref = [skills.resolve_skill("fix", repo, CFG)]
    shims.generate_shims(worktree, ["claude"], ref)
    shims.generate_shims(worktree, ["claude"], ref)
    exclude = (repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert exclude.count(".claude/skills/factory-*") == 1 and exclude.count(".agents/skills/factory-*") == 1


def test_shims_in_a_second_worktree_are_also_hidden(repo, worktree, tmp_path):
    shims.generate_shims(worktree, ["claude"], [skills.resolve_skill("fix", repo, CFG)])
    wt2 = tmp_path / "wt2"
    git(repo, "worktree", "add", "-q", "-b", "run-2", str(wt2))  # created after the patterns exist
    shims.generate_shims(wt2, ["claude"], [skills.resolve_skill("fix", repo, CFG)])
    assert porcelain(wt2) == ""


def test_running_generate_shims_twice_changes_nothing(repo, worktree):
    ref = [skills.resolve_skill("fix", repo, CFG)]
    first = shims.generate_shims(worktree, ["claude"], ref)
    inode = (worktree / ".claude" / "skills" / "factory-fix").lstat().st_ino
    second = shims.generate_shims(worktree, ["claude"], ref)
    assert first == second and (worktree / ".claude" / "skills" / "factory-fix").lstat().st_ino == inode


def test_a_shim_that_points_at_an_old_skill_is_replaced(repo, worktree, tmp_path):
    old = make_skill(tmp_path / "old", "fix")
    shims.generate_shims(worktree, ["claude"], [skills.SkillRef("fix", "own", old)])
    new_ref = skills.resolve_skill("fix", repo, CFG)
    shims.generate_shims(worktree, ["claude"], [new_ref])
    assert (worktree / ".claude" / "skills" / "factory-fix").resolve() == new_ref.path.resolve()


def test_only_claude_is_accepted_in_phase_1(repo, worktree):
    with pytest.raises(FactoryError, match="phase 1 accepts only claude"):
        shims.generate_shims(worktree, ["codex"], [])


def test_generate_shims_outside_a_git_worktree_is_refused(tmp_path):
    (tmp_path / "plain").mkdir()
    with pytest.raises(FactoryError):
        shims.generate_shims(tmp_path / "plain", ["claude"], [])


# ---- practice packs (phase 1b mechanism; the shipped language content is not written yet) ----

@pytest.fixture
def packs(tmp_path):
    root = tmp_path / "kit"
    for lang in ("java", "typescript"):
        d = root / "skills" / "own" / "practices" / lang
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: practices-{lang}\ndescription: {lang} rules\n---\ncore\n")
        (d / "review.md").write_text("review checklist\n")
    skills.use_kit(root)
    return root


def test_a_java_only_task_gets_only_the_java_pack_and_a_mixed_task_gets_both(repo, packs):
    assert [p.name for p in skills.practice_packs(["java"], "fix", repo, CFG)] == ["practices-java"]
    assert [p.name for p in skills.practice_packs(["java", "typescript"], "fix", repo, CFG)] == ["practices-java", "practices-typescript"]
    assert skills.practice_packs([], "fix", repo, CFG) == []
    assert skills.practice_packs(["cobol"], "fix", repo, CFG) == []  # no pack: nothing, not an error


def test_review_stages_get_the_review_file_and_others_the_core_rules(repo, packs):
    assert skills.practice_packs(["java"], "review-standards", repo, CFG)[0].args["stage_file"] == "review.md"
    assert skills.practice_packs(["java"], "fix", repo, CFG)[0].args["stage_file"] == "SKILL.md"


def test_packs_are_pointers_never_text(repo, packs):
    ref = skills.practice_packs(["java"], "fix", repo, CFG)[0]
    assert ref.path.is_dir() and not hasattr(ref, "text")


def test_a_team_override_replaces_the_shipped_pack(repo, packs):
    o = repo / ".factory" / "config" / "overrides" / "practices" / "java"
    o.mkdir(parents=True)
    (o / "SKILL.md").write_text("---\nname: practices-java\ndescription: ours\n---\nour rules\n")
    ref = skills.practice_packs(["java"], "fix", repo, CFG)[0]
    assert ref.source == "override" and ref.path == o and "merged_over" not in ref.args


def test_a_team_override_can_be_merged_over_the_shipped_pack(repo, packs):
    o = repo / ".factory" / "config" / "overrides" / "practices" / "java"
    o.mkdir(parents=True)
    (o / "SKILL.md").write_text("---\nname: practices-java\ndescription: ours\nmerge: true\n---\nextra rules\n")
    ref = skills.practice_packs(["java"], "fix", repo, CFG)[0]
    assert ref.source == "override" and ref.args["merged_over"].endswith("practices/java")


def test_a_pack_over_max_lines_is_reported_and_the_limit_is_configurable(repo, packs):
    big = packs / "skills" / "own" / "practices" / "java" / "SKILL.md"
    big.write_text("---\nname: x\ndescription: y\n---\n" + "line\n" * 200)
    found = skills.oversized_packs(repo, CFG)
    assert len(found) == 1 and "java is" in found[0].message and "limit is 150" in found[0].message
    assert skills.oversized_packs(repo, Config(machine={}, repo={"practices": {"max_lines": 500}})) == []
