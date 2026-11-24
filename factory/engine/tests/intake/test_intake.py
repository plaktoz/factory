"""Module 4 acceptance criteria: intake (pick-up, dedupe, invalid requests, run creation) and triage rules.

Each test runs against a temp git repo with a committed kit, a temp factory home, and FakeTracker for GitHub.
"""

import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gitops"))
from gitutil import run as git_run  # noqa: E402

from factory_engine import intake, state  # noqa: E402
from factory_engine.adapters.tracker.fake import FakeTracker  # noqa: E402
from factory_engine.config import Config  # noqa: E402
from factory_engine.errors import FactoryError  # noqa: E402
from factory_engine.triage import check_type_resolved, triage_rules  # noqa: E402
from factory_engine.types import GateContext, GateSpec, Request, Source  # noqa: E402

KEY = "github.com/acme/report"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setattr(state, "factory_home", lambda env=None: h)
    return h


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "report"
    (r / "factory").mkdir(parents=True)
    (r / "factory" / "README.md").write_text("kit\n")
    (r / ".factory" / "config").mkdir(parents=True)
    (r / ".factory" / "config" / "factory.yaml").write_text("base_branch: main\ntracker: github\nharness: claude\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    git_run(r, "add", "-A")
    git_run(r, "commit", "-q", "-m", "kit")
    (r / ".factory" / "inbox").mkdir(parents=True)
    return r


@pytest.fixture
def cfg(tmp_path):
    return Config(machine={"worktree_root": str(tmp_path / "wt"), "worktree_path": "{root}/{repo}/{run_id}"},
                  repo={"base_branch": "main", "repo_key": KEY})


@pytest.fixture
def tracker():
    return FakeTracker()


def issue(ref="acme/report#42", title="Login fails on expired token", body="Steps to reproduce...",
          labels=("bug",)):
    return Source(type="github", ref=ref, title=title, body=body, labels=list(labels), author="alice", files=[])


def inbox_file(repo, rel, text, age=60):
    p = repo / ".factory" / "inbox" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    old = time.time() - age
    os.utime(p, (old, old))
    return p


def settle_folder(folder, age=60):
    old = time.time() - age
    for p in [folder, *folder.iterdir()]:
        os.utime(p, (old, old))


def runs_in(home):
    return sorted(p.name for p in (home / "runs" / KEY).iterdir()) if (home / "runs" / KEY).is_dir() else []


# --- pick-up: one submission is one run ---

def test_inbox_folder_of_three_files_gives_one_run(repo, cfg, tracker, home):
    folder = repo / ".factory" / "inbox" / "new-color"
    folder.mkdir()
    (folder / "a.md").write_text("---\ntitle: New color\ntype: feature\n---\nPart one.\n")
    (folder / "b.md").write_text("Part two.\n")
    (folder / "c.md").write_text("Part three.\n")
    settle_folder(folder)
    report = intake.sync(repo, cfg, tracker)
    assert len(report.created) == 1
    assert len(runs_in(home)) == 1
    req = json.loads((home / "runs" / KEY / runs_in(home)[0] / "request.json").read_text())
    assert req["title"] == "New color"
    assert "Part one." in req["source"]["body"] and "Part three." in req["source"]["body"]


def test_loose_markdown_file_gives_one_run(repo, cfg, tracker, home):
    inbox_file(repo, "pink.md", "---\ntitle: Pink header\n---\nBody.\n")
    report = intake.sync(repo, cfg, tracker)
    assert len(report.created) == 1
    assert len(runs_in(home)) == 1


def test_add_with_files_gives_one_run(repo, cfg, home):
    a = repo / "a.md"
    b = repo / "b.md"
    a.write_text("First file.\n")
    b.write_text("Second file.\n")
    ref = intake.add(repo, cfg, "Two files", files=[a, b])
    assert runs_in(home) == [ref.run_id]


def test_folder_still_receiving_files_waits_for_ten_quiet_seconds(repo, cfg, tracker, home):
    folder = repo / ".factory" / "inbox" / "half-copied"
    folder.mkdir()
    (folder / "a.md").write_text("---\ntitle: Half copied\n---\nOne.\n")
    now = time.time()
    os.utime(folder / "a.md", (now, now))
    os.utime(folder, (now, now))
    assert intake.sync(repo, cfg, tracker).created == []
    assert runs_in(home) == []
    settle_folder(folder, age=11)
    assert len(intake.sync(repo, cfg, tracker).created) == 1
    assert len(runs_in(home)) == 1


# --- dedupe ---

def test_same_source_ref_and_body_never_creates_a_second_run(repo, cfg, tracker, home):
    tracker.add(issue())
    first = intake.sync(repo, cfg, tracker)
    second = intake.sync(repo, cfg, tracker)
    assert len(first.created) == 1
    assert second.created == [] and second.duplicates == ["acme/report#42"]
    assert len(runs_in(home)) == 1


def test_a_duplicate_found_in_the_archive_is_skipped(repo, cfg, tracker, home):
    body_sha = intake.normalize(issue(), cfg).body_sha
    archive = home / "archive" / KEY / "2026-10"
    archive.mkdir(parents=True)
    req = {"source": {"ref": "acme/report#42"}, "body_sha": body_sha}
    with zipfile.ZipFile(archive / "old-run-abcde.zip", "w") as z:
        z.writestr("old-run-abcde/request.json", json.dumps(req))
    tracker.add(issue())
    report = intake.sync(repo, cfg, tracker)
    assert report.created == [] and report.duplicates == ["acme/report#42"]


def test_a_markdown_status_write_does_not_change_dedupe(repo, cfg, tracker, home):
    inbox_file(repo, "stable.md", "---\ntitle: Stable\n---\nSame body.\n")
    intake.sync(repo, cfg, tracker)
    text = (repo / ".factory" / "inbox" / "stable.md").read_text()
    assert "factory_run:" in text
    report = intake.sync(repo, cfg, tracker)
    assert report.created == [] and len(runs_in(home)) == 1


def test_a_changed_body_while_the_run_is_active_logs_and_raises_attention(repo, cfg, tracker, home):
    tracker.add(issue())
    run_id = intake.sync(repo, cfg, tracker).created[0].run_id
    tracker.items[0] = issue(body="A different body after an edit.")
    report = intake.sync(repo, cfg, tracker)
    assert report.created == [] and report.changed == ["acme/report#42"]
    assert runs_in(home) == [run_id]
    run_dir = home / "runs" / KEY / run_id
    events = [e.type for e in state.read_events(run_dir)]
    assert "request_changed" in events
    run = state.read_run(run_dir)
    assert run.attention is not None and run.attention.kind == "request_changed"
    assert run.status == "pending"


def test_the_same_ref_with_a_changed_body_never_starts_a_second_run_through_intake(repo, cfg, tracker, home):
    """Module 4: a repeat sync of the same source ref and body hash never creates a second run. A changed body is not a
    duplicate: while its run is active it is logged, and no second run starts; the body-hash half is checked here."""
    tracker.add(issue())
    first = intake.sync(repo, cfg, tracker).created[0]
    original_sha = state.read_run(first.run_dir).request.body_sha
    tracker.items[0] = issue(body="A different body after an edit.")
    second = intake.sync(repo, cfg, tracker)
    assert second.created == [] and second.duplicates == []
    assert runs_in(home) == [first.run_id]
    assert state.read_run(first.run_dir).request.body_sha == original_sha  # the run keeps the body it started with
    assert intake.normalize(issue(body="A different body after an edit."), cfg).body_sha != original_sha


def test_a_changed_body_logs_request_changed_once(repo, cfg, tracker, home):
    tracker.add(issue())
    run_id = intake.sync(repo, cfg, tracker).created[0].run_id
    tracker.items[0] = issue(body="edited")
    intake.sync(repo, cfg, tracker)
    intake.sync(repo, cfg, tracker)
    changed = [e for e in state.read_events(home / "runs" / KEY / run_id) if e.type == "request_changed"]
    assert len(changed) == 1


# --- invalid requests ---

def test_github_request_without_title_is_labelled_and_creates_no_run(repo, cfg, tracker, home):
    tracker.add(issue(title=""))
    report = intake.sync(repo, cfg, tracker)
    assert report.created == [] and report.invalid == ["acme/report#42"]
    assert tracker.last_status("acme/report#42") == "factory:invalid"
    comment = [c.comment for c in tracker.statuses if c.status == "factory:invalid"][0]
    assert "no title" in comment
    assert runs_in(home) == []


def test_invalid_github_request_is_marked_once(repo, cfg, tracker, home):
    tracker.add(issue(title=""))
    intake.sync(repo, cfg, tracker)
    # GitHub lists the label back on the issue after the status write; FakeTracker does not, so the test adds it.
    tracker.items[0] = issue(title="", labels=("bug", "factory:invalid"))
    intake.sync(repo, cfg, tracker)
    assert len([c for c in tracker.statuses if c.status == "factory:invalid"]) == 1


def test_markdown_request_without_title_gets_factory_error_and_no_run(repo, cfg, tracker, home):
    path = inbox_file(repo, "untitled.md", "Just a body, no heading or title.\n")
    report = intake.sync(repo, cfg, tracker)
    assert report.created == [] and report.invalid == [".factory/inbox/untitled.md"]
    assert "factory_error:" in path.read_text()
    assert runs_in(home) == []


def test_unknown_type_is_refused_with_the_reason(repo, cfg, tmp_path):
    path = tmp_path / "typed.md"
    path.write_text("---\ntype: weird\n---\nbody\n")
    src = Source(type="markdown", ref="typed.md", title="t", body="body", labels=[], author=None, files=[path])
    with pytest.raises(FactoryError) as e:
        intake.normalize(src, cfg)
    assert e.value.code == "intake.invalid" and "weird" in e.value.message


def test_broken_front_matter_is_invalid_and_does_not_stop_the_sync(repo, cfg, tracker, home):
    bad = inbox_file(repo, "broken.md", "---\ntitle: [unclosed\n---\nBody.\n")
    tracker.add(issue())
    report = intake.sync(repo, cfg, tracker)
    assert report.invalid == [".factory/inbox/broken.md"]
    assert len(report.created) == 1
    assert "factory_error:" in bad.read_text()


# --- run id ---

def test_run_id_avoids_an_existing_branch(repo, cfg, home, monkeypatch):
    git_run(repo, "branch", "fix-login-aaaaa")  # the first candidate the stub below produces is taken

    class Stub:
        def __init__(self):
            self.n = 0

        def choice(self, alphabet):
            self.n += 1
            return "a" if self.n <= 5 else "b"

    monkeypatch.setattr(state, "secrets", Stub())
    ref = intake.add(repo, cfg, "Fix login")
    assert ref.run_id == "fix-login-bbbbb"


def test_run_id_format_is_slug_then_five_characters(repo, cfg, home):
    ref = intake.add(repo, cfg, "Pink header colour!")
    assert len(ref.run_id.rsplit("-", 1)[1]) == 5
    assert ref.run_id.startswith("pink-header-colour-")


def test_a_run_id_taken_under_another_repo_key_is_avoided(repo, cfg, home, monkeypatch):
    """Acceptance (module 6A): run ids are unique across the whole factory home, not only within one repo. The
    first candidate is held by a run folder under a different repo key; the next candidate must be used."""
    (home / "runs" / "github.com/acme/other" / "fix-login-aaaaa").mkdir(parents=True)

    class Stub:
        def __init__(self):
            self.n = 0

        def choice(self, alphabet):
            self.n += 1
            return "a" if self.n <= 5 else "d"

    monkeypatch.setattr(state, "secrets", Stub())
    assert intake.add(repo, cfg, "Fix login").run_id == "fix-login-ddddd"


def test_run_id_never_matches_an_existing_run_folder(repo, cfg, tracker, home, monkeypatch):
    (home / "runs" / KEY / "fix-login-aaaaa").mkdir(parents=True)

    class Stub:
        def __init__(self):
            self.n = 0

        def choice(self, alphabet):
            self.n += 1
            return "a" if self.n <= 5 else "c"

    monkeypatch.setattr(state, "secrets", Stub())
    assert intake.add(repo, cfg, "Fix login").run_id == "fix-login-ccccc"


# --- a created run ---

def test_created_run_has_request_run_json_paths_and_the_queued_label(repo, cfg, tracker, home):
    tracker.add(issue())
    ref = intake.sync(repo, cfg, tracker).created[0]
    run_dir = home / "runs" / KEY / ref.run_id
    assert (run_dir / "request.json").is_file()
    run = state.read_run(run_dir)
    assert run.workflow is None and run.status == "pending"
    assert run.paths["run_dir"] == str(run_dir)
    assert run.paths["repo"] == str(repo)
    assert tracker.last_status("acme/report#42") == "factory:queued"
    assert run.kit_hash


def test_worktree_and_branch_are_not_created_until_triage(repo, cfg, tracker, home):
    tracker.add(issue())
    ref = intake.sync(repo, cfg, tracker).created[0]
    run = state.read_run(ref.run_dir)
    assert not run.worktree.exists()
    branches = subprocess.run(["git", "-C", str(repo), "branch", "--list", ref.run_id],
                              capture_output=True, text=True).stdout
    assert branches.strip() == ""


def test_no_skill_shims_exist_before_triage_because_no_worktree_does(repo, cfg, tracker, home):
    """Shims are generated only inside a worktree, and intake never creates one, so nothing shim-shaped exists yet:
    no `factory-*` link under the reserved worktree and no shim exclude pattern written to the repo (module 10)."""
    tracker.add(issue())
    ref = intake.sync(repo, cfg, tracker).created[0]
    run = state.read_run(ref.run_dir)
    assert not run.worktree.exists()
    shims = [p for p in repo.rglob("factory-*") if ".git" not in p.parts]
    assert shims == [], f"intake made shim-shaped folders before triage: {shims}"
    assert not (run.worktree / ".claude" / "skills").exists()
    exclude = repo / ".git" / "info" / "exclude"
    assert not exclude.exists() or ".claude/skills/factory-*" not in exclude.read_text()


def test_markdown_request_file_gets_factory_run_front_matter(repo, cfg, tracker, home):
    path = inbox_file(repo, "gets-status.md", "---\ntitle: Gets status\n---\nBody.\n")
    ref = intake.sync(repo, cfg, tracker).created[0]
    text = path.read_text()
    assert f"factory_run: {ref.run_id}" in text and "factory_status: queued" in text


# --- triage rules ---

def make_request(*, type=None, type_source=None, labels=(), title="Plain title", body="Plain body."):
    src = Source(type="github", ref="acme/report#7", title=title, body=body, labels=list(labels), author=None, files=[])
    return Request(request_id="gh-7", source=src, body_sha="abc", repo="report", title=title, type=type,
                   type_source=type_source, priority=None, acceptance=[])


def test_explicit_type_wins_over_every_other_rule(cfg):
    req = make_request(type="research", type_source="explicit", labels=("bug",), title="Fix crash")
    r = triage_rules(req, cfg)
    assert (r.type, r.workflow, r.type_source) == ("research", "research", "explicit")


def test_a_type_label_wins_over_front_matter_and_keywords(cfg):
    req = make_request(type="chore", type_source="front_matter", labels=("feature",), title="Fix crash")
    r = triage_rules(req, cfg)
    assert (r.type, r.type_source) == ("feature", "label")
    assert r.workflow == "feature"


def test_front_matter_type_wins_over_keywords(cfg):
    req = make_request(type="chore", type_source="front_matter", title="Fix crash")
    r = triage_rules(req, cfg)
    assert (r.type, r.type_source) == ("chore", "front_matter")


def test_keyword_rule_records_its_source_and_workflow(cfg):
    r = triage_rules(make_request(title="Login fails on expired token"), cfg)
    assert (r.type, r.workflow, r.type_source) == ("bug", "bug-fix", "keyword")
    assert 0 < r.confidence < 1


def test_no_rule_decides_gives_no_type_for_the_llm_to_fill(cfg):
    r = triage_rules(make_request(title="Thoughts on the roadmap", body="Open question."), cfg)
    assert r.type is None and r.workflow is None and r.confidence == 0.0
    assert r.type_source == "keyword"


def test_several_keyword_types_do_not_guess(cfg):
    r = triage_rules(make_request(title="Investigate and fix the login bug"), cfg)
    assert r.type is None


def test_the_rules_never_return_llm(cfg):
    for req in (make_request(), make_request(title="Add a button"), make_request(type="bug", type_source="explicit")):
        assert triage_rules(req, cfg).type_source != "llm"


def test_type_resolved_gate_passes_only_with_a_type_and_workflow(tmp_path, cfg):
    out = tmp_path / "triage.json"
    spec = GateSpec(kind="check", cmd=None, check="type-resolved", schema=None, args={})

    def ctx():
        return GateContext(run=None, stage="triage", task_id="classify", worktree=tmp_path, task_dir=None,
                           artifact=out, task_base=None, scope=[], deny=[], cfg=cfg)

    assert not check_type_resolved(spec, ctx()).passed
    out.write_text(json.dumps({"type": None, "workflow": None}))
    assert not check_type_resolved(spec, ctx()).passed
    out.write_text(json.dumps({"type": "bug", "workflow": "bug-fix"}))
    assert check_type_resolved(spec, ctx()).passed


# --- triage candidates: only workflows that load ---

def _kit_loads(repo, cfg):
    """The driver's `loads`: a workflow loads when module 5's loader accepts it. Used here to test against the real kit."""
    from factory_engine.workflow import load_workflow

    def loads(wid):
        try:
            load_workflow(repo, cfg, wid)
            return True
        except FactoryError:
            return False
    return loads


def test_triage_candidates_offer_only_workflows_that_load(repo, cfg):
    from factory_engine.triage import TYPE_WORKFLOW, triage_candidates
    loads = _kit_loads(repo, cfg)
    offered = [wid for wid, _, _ in triage_candidates(make_request(title="Something vague"), loads)]
    assert offered == sorted(offered)  # equal keyword hits (none) fall back to workflow id order
    assert offered and all(loads(wid) for wid in offered)
    # the shipped kit has bug-fix and chore only; feature, new-app and research are phase 1b and do not load yet
    assert set(offered) == {"bug-fix", "chore"}
    assert set(TYPE_WORKFLOW.values()) - set(offered) == {"feature", "new-app", "research"}


def test_a_workflow_that_does_not_load_is_never_offered_even_when_its_keywords_match(repo, cfg):
    from factory_engine.triage import triage_candidates
    req = make_request(title="Add support for dark mode and implement the toggle")  # feature keywords only
    ids = [wid for wid, _, _ in triage_candidates(req, _kit_loads(repo, cfg))]
    assert "feature" not in ids


def test_the_better_keyword_match_is_offered_first(cfg):
    from factory_engine.triage import triage_candidates
    req = make_request(title="Login crash after upgrade", body="It fails with an exception on every call.")
    first, second = triage_candidates(req, lambda wid: wid in {"bug-fix", "chore"})
    assert first[0] == "bug-fix" and "crash" in first[2]
    assert second[0] == "chore"


def test_candidates_never_exceed_the_packets_four_options(cfg):
    from factory_engine.triage import triage_candidates
    assert len(triage_candidates(make_request(), lambda wid: True)) == 4


def test_with_fewer_than_two_loading_workflows_the_list_is_too_short_for_a_triage_stop(cfg):
    from factory_engine.triage import triage_candidates
    assert len(triage_candidates(make_request(), lambda wid: wid == "bug-fix")) == 1
    assert triage_candidates(make_request(), lambda wid: False) == []


def test_the_candidates_make_a_valid_triage_packet(repo, cfg):
    from factory_engine import decisions as D
    from factory_engine.triage import triage_candidates
    from factory_engine.validate import validate
    packet = D.triage_packet(triage_candidates(make_request(), _kit_loads(repo, cfg)))
    validate(packet, "packet")
