"""Module 13 acceptance criteria for delivery: the merge policy, auto-merge, sinks, ADR and report names."""

import json
import re
import subprocess
from pathlib import Path

import pytest

from factory_engine import decisions, delivery, gitops, notes, state, usage
from factory_engine.adapters.tracker.fake import FakeTracker
from factory_engine.errors import FactoryError
from factory_engine.fake_prs import FakePullRequests
from factory_engine.gh import GitHubPullRequests
from factory_engine.state import read_run
from factory_engine.types import PrRef, StageState
from factory_engine.summary import render_summary
from factory_engine.yamlio import load_yaml

from delivery_helpers import POLICY, commit_change, git, make_run, pass_gates, set_run, write_task

NO_WORKFLOWS = POLICY.replace("workflows: [chore]", "workflows: []")


def rule(decision, name):
    return next(r for r in decision.rules if r.rule == name)


def chore(home, tmp_path, cfg, **kw):
    """A chore run whose gates passed and whose one-line change is committed on the run branch."""
    run_dir, wt, repo = make_run(home, tmp_path, cfg, **kw)
    commit_change(wt, {"app/main.py": "x = 2\n"})
    pass_gates(run_dir, "scope-diff", "lint-clean")
    return run_dir, wt, repo


def changed(wt):
    return gitops.changed_files(wt, "origin/main")


def evaluate(run_dir, cfg, wt, ci="green"):
    return delivery.evaluate_merge(run_dir, cfg, changed=changed(wt), ci=ci)


def set_type_source(run_dir, source):
    run = state.read_run(run_dir)
    run.request.type_source = source
    set_run(run_dir, request=run.request)


def approve(run_dir, stage, by="alice", notes_text=None):
    sha = decisions.request(run_dir, stage, 1, kind="approval")
    decisions.record(run_dir, stage, 1, packet_sha=sha, choices={"D1": "approve"}, by=by, channel="cli",
                     notes=notes_text or "")


# --- merge policy -------------------------------------------------------------------------------------------------

def test_a_small_explicit_chore_with_green_ci_is_auto_and_the_same_change_typed_by_llm_is_not(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    assert evaluate(run_dir, cfg, wt, ci="green").auto is True
    set_type_source(run_dir, "llm")
    typed_by_llm = evaluate(run_dir, cfg, wt, ci="green")
    assert typed_by_llm.auto is False
    assert rule(typed_by_llm, "auto.type_source").passed is False


@pytest.mark.parametrize("case", ["protected_path", "dependency_manifest", "note_used",
                                  "architecture_decision", "skipped_gate"])
def test_any_protected_path_dependency_change_used_note_architecture_decision_or_skipped_gate_gives_auto_false_with_that_rule_named(
        case, home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    if case == "protected_path":
        commit_change(wt, {"auth/session.py": "y = 1\n"})
        rule_name = "never_auto_if.paths"
    elif case == "dependency_manifest":
        commit_change(wt, {"package.json": "{}\n"})
        rule_name = "never_auto_if.dependency_manifests_changed"
    elif case == "note_used":
        write_task(run_dir, "change", "running")
        notes.queue_note(run_dir, "change", "keep the old name", by="me")
        rule_name = "never_auto_if.notes_used"
    elif case == "architecture_decision":
        approve(run_dir, "architecture")
        rule_name = "never_auto_if.architecture_decision"
    else:
        set_run(run_dir, stages=[StageState("implement", 1, "done", [], "t0", "t1"),
                                 StageState("verify", 1, "skipped", [], None, None)])
        rule_name = "auto.require.gates"
    d = evaluate(run_dir, cfg, wt)
    assert d.auto is False
    named = rule(d, rule_name)
    assert named.passed is False
    assert named.detail in d.reason  # the pull request says why in words, not only in merge.json
    assert json.loads((run_dir / "merge.json").read_text())["auto"] is False


def test_auto_merge_is_requested_through_githubs_auto_merge_flag(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    prs = FakePullRequests()
    pr = prs.create(wt, base="main", head="tidy-ab12c", title="t", body_file=_body(run_dir), labels=[])
    prs.set_ci(pr, "green")
    delivery.merge_or_request_review(pr, evaluate(run_dir, cfg, wt), prs, reviewers=["bob"])
    assert prs.prs[pr.number].auto_merge is True
    assert prs.prs[pr.number].merged_with == "squash"
    assert prs.prs[pr.number].state == "merged"


def test_with_no_auto_workflows_a_small_chore_is_not_auto_with_the_reason_named(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg, kit_files={".factory/config/merge-policy.yaml": NO_WORKFLOWS})
    d = evaluate(run_dir, cfg, wt)
    assert d.auto is False
    assert d.reason == "chore is not in the auto workflows"


def test_merge_json_holds_every_rule_with_its_result(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg, kit_files={".factory/config/merge-policy.yaml": NO_WORKFLOWS})
    evaluate(run_dir, cfg, wt)
    doc = json.loads((run_dir / "merge.json").read_text())
    names = [r["rule"] for r in doc["rules"]]
    assert {"auto.workflows", "auto.type_source", "auto.require.ci", "auto.require.max_files",
            "auto.require.max_lines", "auto.require.gates"} <= set(names)
    assert doc["auto"] is False and doc["reason"] == "chore is not in the auto workflows"


def test_the_merge_json_the_engine_writes_validates_against_its_schema(home, tmp_path, cfg):
    """Issue #88: merge.json has a schema, and a real evaluation (auto and not auto) writes a file that matches it."""
    from factory_engine.validate import validate
    for policy, auto, run_id in ((POLICY, True, "tidy-aaaaa"), (NO_WORKFLOWS, False, "tidy-bbbbb")):
        run_dir, wt, _ = chore(home, tmp_path / run_id, cfg, run_id=run_id,
                               kit_files={".factory/config/merge-policy.yaml": policy})
        evaluate(run_dir, cfg, wt)
        doc = json.loads((run_dir / "merge.json").read_text())
        validate(doc, "merge", file=str(run_dir / "merge.json"))
        assert doc["auto"] is auto


MERGE = {"auto": False, "reason": "chore is not in the auto workflows", "ci": "green",
         "rules": [{"rule": "auto.workflows", "passed": False, "detail": "chore is not in the auto workflows"}]}


@pytest.mark.parametrize("break_it", [
    lambda d: d.pop("rules"),
    lambda d: d["rules"][0].update(passed="yes"),
    lambda d: d["rules"][0].pop("detail"),
    lambda d: d.update(auto="false"),
    lambda d: d.pop("reason"),
    lambda d: d.pop("ci"),
], ids=["no rules", "passed not a boolean", "no detail", "auto not a boolean", "no reason", "no ci"])
def test_a_malformed_merge_json_fails_validation(break_it):
    import copy
    from factory_engine.validate import validate
    validate(MERGE, "merge")                     # the good one passes, so each failure below is the break and nothing else
    bad = copy.deepcopy(MERGE)
    break_it(bad)
    with pytest.raises(FactoryError) as err:
        validate(bad, "merge", file="merge.json")
    assert err.value.code == "config.invalid"


def test_a_red_ci_check_blocks_auto(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    d = evaluate(run_dir, cfg, wt, ci="red")
    assert d.auto is False and rule(d, "auto.require.ci").passed is False


def _review(run_dir, findings, *, task="standards"):
    """A review stage whose one task wrote review-findings.json with these findings (None: write nothing)."""
    folder = run_dir / "tasks" / task
    folder.mkdir(parents=True, exist_ok=True)
    if findings is not None:
        (folder / "review.json").write_text(json.dumps({"schema_version": 1, "findings": findings}))
    set_run(run_dir, stages=[StageState("review", 1, "done", [task], "t0", "t1")])


def _finding(severity, rule="review-standards"):
    return {"file": "app/main.py", "line": 1, "severity": severity, "rule": rule}


def test_a_review_stage_with_only_low_findings_does_not_block_auto(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    _review(run_dir, [_finding("low")])
    d = evaluate(run_dir, cfg, wt)
    assert rule(d, "never_auto_if.review_findings_at_or_above").passed is True


def test_a_medium_or_high_finding_blocks_auto_and_names_the_rule(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    _review(run_dir, [_finding("low"), _finding("high", rule="review-spec")])
    d = evaluate(run_dir, cfg, wt)
    assert d.auto is False
    r = rule(d, "never_auto_if.review_findings_at_or_above")
    assert r.passed is False and "high" in r.detail and "review-spec" in r.detail


def test_a_review_stage_with_no_artifact_blocks_auto_because_the_findings_are_unknown(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    _review(run_dir, None)
    d = evaluate(run_dir, cfg, wt)
    assert d.auto is False
    assert rule(d, "never_auto_if.review_findings_at_or_above").passed is False


def test_a_review_artifact_that_fails_the_schema_blocks_auto(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    _review(run_dir, [{"file": "app/main.py"}])  # no severity, rule or line
    d = evaluate(run_dir, cfg, wt)
    assert d.auto is False
    assert rule(d, "never_auto_if.review_findings_at_or_above").passed is False


def test_two_rework_loops_block_auto(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    run = state.read_run(run_dir)
    run.loops = {"verify->implement": 2}
    set_run(run_dir, loops=run.loops)
    d = evaluate(run_dir, cfg, wt)
    assert d.auto is False
    assert rule(d, "never_auto_if.rework_loops_used_at_least").passed is False


def test_a_missing_kit_policy_fails_closed_to_human(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    (home / "kits" / "kit1" / ".factory" / "config" / "merge-policy.yaml").unlink()
    assert evaluate(run_dir, cfg, wt).auto is False


# --- auto-merge and human review ----------------------------------------------------------------------------------

def test_a_human_decision_requests_reviewers_and_does_not_merge(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg, kit_files={".factory/config/merge-policy.yaml": NO_WORKFLOWS})
    prs = FakePullRequests()
    pr = prs.create(wt, base="main", head="tidy-ab12c", title="t", body_file=_body(run_dir), labels=[])
    delivery.merge_or_request_review(pr, evaluate(run_dir, cfg, wt), prs, reviewers=["bob"])
    assert prs.prs[pr.number].reviewers == ["bob"]
    assert "merge" not in prs.calls


def test_a_merge_refused_by_branch_protection_needs_a_human(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    prs = FakePullRequests()
    pr = prs.create(wt, base="main", head="tidy-ab12c", title="t", body_file=_body(run_dir), labels=[])
    prs.fail_next = FactoryError("git.command_failed", "gh pr merge: the base branch policy prohibits the merge")
    with pytest.raises(FactoryError) as e:
        delivery.merge_or_request_review(pr, evaluate(run_dir, cfg, wt), prs, reviewers=[])
    assert e.value.code == "delivery.merge_blocked" and e.value.kind == "human"


def test_a_merge_refused_because_the_repo_does_not_allow_auto_merge_needs_a_human(home, tmp_path, cfg):
    """The real adapter, with the exact stderr gh printed against a real repo that has 'Allow auto-merge' off (item 23,
    checked 2026-11-24 on plaktoz/factory-gc-scratch, exit 1)."""
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    gh_stderr = "GraphQL: Auto merge is not allowed for this repository (enablePullRequestAutoMerge)\n"
    seen: list[list[str]] = []

    def gh(args):
        seen.append(args)
        return subprocess.CompletedProcess(args, 1, "", gh_stderr)

    prs = GitHubPullRequests("acme/report", gh)
    pr = PrRef(number=12, url="https://github.com/acme/report/pull/12", head="tidy-ab12c", base="main")
    with pytest.raises(FactoryError) as e:
        delivery.merge_or_request_review(pr, evaluate(run_dir, cfg, wt), prs, reviewers=[])
    assert e.value.code == "delivery.merge_blocked" and e.value.kind == "human"
    assert seen == [["pr", "merge", "12", "-R", "acme/report", "--squash", "--auto", "--delete-branch"]]


def test_watch_pr_reports_red_ci_for_rework_and_a_closed_pr(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    prs = FakePullRequests()
    pr = prs.create(wt, base="main", head="tidy-ab12c", title="t", body_file=_body(run_dir), labels=[])
    set_run(run_dir, pr=pr)
    prs.set_ci(pr, "red", "lint: failed")
    state_ = delivery.watch_pr(run_dir, prs)
    assert (state_.state, state_.ci, state_.checks_output) == ("open", "red", "lint: failed")
    prs.close(pr)
    assert delivery.watch_pr(run_dir, prs).state == "closed"


def test_watch_pr_writes_merged_once_when_the_pr_is_merged(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    prs = FakePullRequests()
    pr = prs.create(wt, base="main", head="tidy-ab12c", title="t", body_file=_body(run_dir), labels=[])
    set_run(run_dir, pr=pr)
    prs.human_merge(pr)
    assert delivery.watch_pr(run_dir, prs).state == "merged"
    delivery.watch_pr(run_dir, prs)
    assert [e.type for e in state.read_events(run_dir)].count("merged") == 1


def test_a_failed_pr_creation_is_transient_and_the_run_has_no_pr_yet(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    render_summary(run_dir, usage.summarize([run_dir]))
    prs = FakePullRequests()
    prs.fail_next = FactoryError("git.command_failed", "gh pr create: boom")
    with pytest.raises(FactoryError) as e:
        delivery.open_pr(run_dir, cfg, prs)
    assert (e.value.code, e.value.kind) == ("git.network", "transient")
    assert state.read_run(run_dir).pr is None


# --- summary ------------------------------------------------------------------------------------------------------

def test_the_summary_has_request_stages_evidence_decisions_notes_usage_and_merge_result_from_state(
        home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    set_run(run_dir, stages=[StageState("implement", 1, "done", ["change"], "t0", "t1"),
                             StageState("verify", 1, "done", [], "t2", "t3")],
            loops={"verify->implement": 1})
    junit = run_dir / "tasks" / "check" / "work" / "check.junit.xml"
    junit.parent.mkdir(parents=True)
    junit.write_text('<testsuite><testcase name="a"/><testcase name="b"><failure/></testcase></testsuite>')
    approve(run_dir, "architecture", by="alice", notes_text="keep it small")
    write_task(run_dir, "change", "running")
    notes.queue_note(run_dir, "change", "use the old name", by="me")
    attempt = usage.start_attempt(run_dir, state.read_run(run_dir), "change", stage="implement", harness="claude",
                                  model_requested=None)
    usage.finish_attempt(run_dir, "change", attempt, exit="ok", input_tokens=100, output_tokens=40,
                         models=["claude-opus-5-5"])
    evaluate(run_dir, cfg, wt)

    text = render_summary(run_dir, usage.summarize([run_dir])).read_text()

    assert "Request: note.md" in text and "Result: running" in text
    assert "implement done (1 rework from verify)" in text and "verify done" in text
    assert "Tests 1 passed, 1 failed" in text and "Scope check passed" in text
    assert "Approve architecture: Approve (by alice)" in text and "architecture note: keep it small" in text
    assert "Note to change by me: use the old name" in text
    assert "claude-opus-5-5: 1 attempt, 140 tokens" in text
    assert "Human review: an architecture decision was approved; a human steered the run with notes" in text


def test_the_summary_lists_the_changed_files_when_the_base_is_not_main_and_there_is_no_remote(home, tmp_path, cfg):
    """Item 37: a local-only repo whose base is not main still lists what the run changed. The base comes from the
    config, and no pull request exists yet (so run.pr is None)."""
    import subprocess
    from factory_engine.types import Request, Source
    cfg.repo["base_branch"] = "tutorial-base"
    repo = tmp_path / "scratch"
    subprocess.run(["git", "init", "-q", "-b", "tutorial-base", str(repo)], check=True)
    (repo / "app").mkdir()
    (repo / "app" / "main.py").write_text("x = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    wt = gitops.create_run_worktree(repo, cfg, "tidy-ab12c", base="tutorial-base", detached=False)
    commit_change(wt, {"app/main.py": "x = 2\n"})
    request = Request("r-1", Source("cli", "note.md", "t", "b", [], None, []), "sha", "scratch", "Tidy the app", "chore",
                      "explicit", None, [])
    run_dir = state.init_run(home, repo, "local/scratch", "tidy-ab12c", request, branch="tidy-ab12c", worktree=wt,
                             kit_hash="kit1").run_dir
    text = render_summary(run_dir, usage.summarize([run_dir]), base=cfg.repo["base_branch"]).read_text()
    assert "Not available" not in text and "app/main.py" in text


def test_the_summary_is_the_pull_request_body(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    render_summary(run_dir, usage.summarize([run_dir]))
    prs = FakePullRequests()
    result = delivery.write_sink(run_dir, cfg, tracker=FakeTracker(), prs=prs)
    assert result.sink == "pull_request"
    body = prs.prs[result.pr.number].body
    assert body.startswith(f"# {run_dir.name}")


def test_a_github_request_gets_closes_on_the_pull_request_summary(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg, source_type="github", ref="acme/report#42")
    render_summary(run_dir, usage.summarize([run_dir]))
    assert "Closes #42" in (run_dir / "summary.md").read_text()


# --- sinks --------------------------------------------------------------------------------------------------------

def test_a_read_only_run_with_an_in_repo_doc_sink_creates_its_branch_only_at_delivery_and_opens_a_pr(
        home, tmp_path, cfg):
    run_dir, wt, repo = make_run(home, tmp_path, cfg, workflow="research", write=False, source_type="github",
                                 ref="acme/report#7", run_id="research-q1w2e")
    (run_dir / "tasks" / "gather" / "work").mkdir(parents=True)
    (run_dir / "tasks" / "gather" / "work" / "report.md").write_text("# Findings\n")
    render_summary(run_dir, usage.summarize([run_dir]))
    assert git(wt, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"  # detached, no branch yet
    assert git(repo, "branch", "--list", "--format=%(refname:short)", "research-q1w2e") == ""

    prs = FakePullRequests()
    result = delivery.write_sink(run_dir, cfg, tracker=FakeTracker(), prs=prs)

    assert result.sink == "doc" and result.pr is not None
    assert git(repo, "branch", "--list", "--format=%(refname:short)", "research-q1w2e") == "research-q1w2e"
    assert prs.prs[result.pr.number].ref.head == "research-q1w2e"
    assert git(wt, "show", "HEAD:docs/research/research-q1w2e.md") == "# Findings"


def test_a_comment_sink_on_a_github_request_posts_the_summary_to_the_issue(home, tmp_path, cfg):
    run_dir, wt, _ = make_run(home, tmp_path, cfg, workflow="ask", write=False, source_type="github",
                              ref="acme/report#42")
    render_summary(run_dir, usage.summarize([run_dir]))
    tracker = FakeTracker()
    result = delivery.write_sink(run_dir, cfg, tracker=tracker, prs=FakePullRequests())
    assert result.sink == "comment" and result.pr is None
    call = tracker.statuses[0]
    assert (call.ref, call.status) == ("acme/report#42", "factory:done")
    assert "# tidy-ab12c" in call.comment


def test_a_comment_sink_on_a_markdown_request_appends_the_summary_to_its_file(home, tmp_path, cfg):
    request = tmp_path / "question.md"
    request.write_text("What is up?\n")
    run_dir, wt, _ = make_run(home, tmp_path, cfg, workflow="ask", write=False, source_type="markdown",
                              ref="question.md", source_files=[request])
    render_summary(run_dir, usage.summarize([run_dir]))
    delivery.write_sink(run_dir, cfg, tracker=FakeTracker(), prs=FakePullRequests())
    text = request.read_text()
    assert text.startswith("What is up?") and "## Answer" in text and "# tidy-ab12c" in text


# --- ADR and report names -----------------------------------------------------------------------------------------

def test_adr_and_report_names_contain_the_run_id_never_a_counter(home, tmp_path, cfg):
    run_dir, wt, repo = chore(home, tmp_path, cfg)
    assert delivery.write_adr(run_dir, wt) is None  # no architecture decision approved: no ADR
    approve(run_dir, "architecture")
    adr = delivery.write_adr(run_dir, wt)
    assert adr is not None
    assert adr.parent == wt / "docs" / "adr"
    assert re.fullmatch(rf"\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(run_dir.name)}\.md", adr.name)
    assert "docs/adr/" in git(wt, "show", "--name-only", "--format=", "HEAD")


def test_an_adr_starts_with_front_matter_naming_its_scope_status_and_supersedes(home, tmp_path, cfg):
    run_dir, wt, repo = chore(home, tmp_path, cfg)
    approve(run_dir, "architecture")
    text = delivery.write_adr(run_dir, wt).read_text()
    assert text.startswith("---\n")
    front, _, body = text[4:].partition("\n---\n")
    meta = load_yaml(front)
    assert meta == {"scope": "repo", "repo": read_run(run_dir).repo, "topic": "architecture", "status": "accepted",
                    "supersedes": []}
    assert body.lstrip().startswith("# ")


def test_the_research_report_name_is_the_run_id(home, tmp_path, cfg):
    run_dir, wt, repo = make_run(home, tmp_path, cfg, workflow="research", write=False, source_type="github",
                                 ref="acme/report#7", run_id="research-q1w2e")
    (run_dir / "tasks" / "gather" / "work").mkdir(parents=True)
    (run_dir / "tasks" / "gather" / "work" / "report.md").write_text("# Findings\n")
    render_summary(run_dir, usage.summarize([run_dir]))
    delivery.write_sink(run_dir, cfg, tracker=FakeTracker(), prs=FakePullRequests())
    assert git(wt, "show", "--name-only", "--format=", "HEAD") == "docs/research/research-q1w2e.md"


def _body(run_dir: Path) -> Path:
    path = run_dir / "summary.md"
    if not path.exists():
        render_summary(run_dir, usage.summarize([run_dir]))
    return path


def test_the_summary_reads_the_review_findings_instead_of_saying_they_cannot_be_read(home, tmp_path, cfg):
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    _review(run_dir, [_finding("high", rule="review-spec")])
    text = render_summary(run_dir, usage.summarize([run_dir])).read_text()
    assert "not readable yet" not in text
    assert "Review findings: 1 read, first: high app/main.py:1 review-spec" in text


# ---- found in the first whole live run (2026-11-22): two lines in the pull request body read as faults ----

def test_a_summary_names_a_command_attempt_as_a_command_and_not_as_an_unknown_model(home, tmp_path, cfg):
    """`rules` and `check` are shell commands: they run no model, so they have no model name and no tokens. The summary
    says so instead of printing `unknown: 2 attempts, tokens unknown`, which reads as a missing model."""
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    for task in ("rules", "check"):
        attempt = usage.start_attempt(run_dir, state.read_run(run_dir), task, stage="verify", harness="command",
                                      model_requested=None)
        usage.finish_attempt(run_dir, task, attempt, exit="ok", input_tokens=None, output_tokens=None, models=[])
    attempt = usage.start_attempt(run_dir, state.read_run(run_dir), "change", stage="implement", harness="claude",
                                  model_requested=None)
    usage.finish_attempt(run_dir, "change", attempt, exit="ok", input_tokens=12, output_tokens=2205, models=["claude-x"])
    text = render_summary(run_dir, usage.summarize([run_dir])).read_text()
    assert "claude-x: 1 attempt, 2,217 tokens" in text
    assert "commands, no model: 2 attempts" in text
    assert "unknown:" not in text


def test_a_summary_still_calls_a_worker_with_no_reported_model_unknown(home, tmp_path, cfg):
    """A Claude attempt whose model could not be read is a real unknown (module 14); only command attempts are renamed."""
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    attempt = usage.start_attempt(run_dir, state.read_run(run_dir), "change", stage="implement", harness="claude",
                                  model_requested=None)
    usage.finish_attempt(run_dir, "change", attempt, exit="ok", input_tokens=5, output_tokens=5, models=[])
    text = render_summary(run_dir, usage.summarize([run_dir])).read_text()
    assert "unknown: 1 attempt, 10 tokens" in text and "commands, no model" not in text


def test_the_pull_request_body_says_the_run_awaits_review_not_that_it_is_running(home, tmp_path, cfg):
    """The body is written as the pull request opens, when run.json still says running. It must name the state the run
    is entering, or a reviewer reads `Result: running` on a pull request that waits for them."""
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    text = render_summary(run_dir, usage.summarize([run_dir]), delivering=True).read_text()
    assert "Result: awaiting review" in text and "Result: running" not in text


def test_no_review_is_requested_when_the_issue_author_opens_the_pull_request(home, tmp_path, cfg):
    """Owner decision D2 (2026-11-24, decision page open-stops-2026-11-24, option ask-nobody-when-author-opens): GitHub drops a
    review request to the pull request's own author, so the factory asks nobody when the author is the one who opens it."""
    run_dir, wt, _ = chore(home, tmp_path, cfg)
    run = read_run(run_dir)
    run.request.source.type = "github"
    run.request.source.author = "plaktoz"
    assert delivery.reviewers_for(run, pr_author="plaktoz") == []
    assert delivery.reviewers_for(run, pr_author="someone-else") == ["plaktoz"]
