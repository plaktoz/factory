"""Module 7, GitHub half: the adapters run against a recorded gh stub, and no GitHub call is made.

The stub replays output shaped like `gh ... --json` (fields checked with `gh issue list --help` and a real
`gh pr view` on this repo). The shape of one statusCheckRollup entry could not be read from this repo, which has no
checks; the entries below follow GitHub's documented fields (name, status, conclusion) and are marked ASSUMED."""

import json
import subprocess

import pytest

from factory_engine.errors import FactoryError
from factory_engine.gh import FileTracker, GitHubPullRequests, GitHubTracker, ci_from_rollup
from factory_engine.types import PrRef


class Stub:
    """Records every gh call and replays a canned result per command prefix."""

    def __init__(self, replies=None):
        self.calls: list[list[str]] = []
        self.replies = replies or {}

    def __call__(self, args):
        self.calls.append(args)
        for prefix, (code, out, err) in self.replies.items():
            if args[: len(prefix)] == list(prefix):
                return subprocess.CompletedProcess(args, code, out, err)
        return subprocess.CompletedProcess(args, 0, "", "")


ISSUES = json.dumps([
    {"number": 42, "title": "Login fails on expired token", "body": "Steps...", "labels": [{"name": "factory"}, {"name": "bug"}],
     "author": {"login": "alice"}, "updatedAt": "2026-11-14T10:00:00Z"},
    {"number": 7, "title": "Old issue", "body": None, "labels": [{"name": "factory"}], "author": None,
     "updatedAt": "2026-11-01T10:00:00Z"},
])


def test_list_new_reads_labelled_open_issues_and_builds_sources():
    stub = Stub({("issue", "list"): (0, ISSUES, "")})
    out = GitHubTracker("acme/report", stub).list_new(None)
    assert [s.ref for s in out] == ["acme/report#42", "acme/report#7"]
    assert out[0].labels == ["factory", "bug"] and out[0].author == "alice" and out[1].body == "" and out[1].author is None
    call = stub.calls[0]
    assert call[:2] == ["issue", "list"] and "--label" in call and call[call.index("--label") + 1] == "factory"
    assert "--state" in call and "open" in call


def _issues(count):
    return json.dumps([{"number": n, "title": f"issue {n}", "body": "", "labels": [], "author": None,
                        "updatedAt": "2026-11-01T00:00:00Z"} for n in range(1, count + 1)])


def test_list_new_passes_limit_200_so_gh_does_not_stop_at_30():
    stub = Stub({("issue", "list"): (0, _issues(3), "")})
    GitHubTracker("acme/report", stub).list_new(None)
    call = stub.calls[0]
    assert call[call.index("--limit") + 1] == "200"


def test_list_new_uses_the_cursor():
    stub = Stub({("issue", "list"): (0, ISSUES, "")})
    out = GitHubTracker("acme/report", stub).list_new("2026-11-10T00:00:00Z")
    assert [s.ref for s in out] == ["acme/report#42"]


def test_set_status_swaps_the_label_and_comments_with_the_link():
    stub = Stub()
    GitHubTracker("acme/report", stub).set_status("acme/report#42", "factory:running", comment="Started run x",
                                                  link="http://127.0.0.1:8765/runs/x")
    edit = next(c for c in stub.calls if c[:2] == ["issue", "edit"])
    assert edit[edit.index("--add-label") + 1] == "factory:running"
    removed = edit[edit.index("--remove-label") + 1].split(",")
    assert "factory:running" not in removed and "factory:queued" in removed and "factory:done" in removed
    comment = next(c for c in stub.calls if c[:2] == ["issue", "comment"])
    assert "Started run x" in comment[comment.index("--body") + 1] and "http://127.0.0.1:8765/runs/x" in comment[comment.index("--body") + 1]


def test_an_unknown_status_label_is_refused_before_any_call():
    stub = Stub()
    with pytest.raises(FactoryError, match="unknown status label"):
        GitHubTracker("acme/report", stub).set_status("42", "factory:nonsense")
    assert stub.calls == []


def test_ensure_labels_creates_each_label():
    stub = Stub()
    GitHubTracker("acme/report", stub).ensure_labels(["factory", "factory:queued"])
    assert [c[2] for c in stub.calls] == ["factory", "factory:queued"]


def test_pr_create_passes_base_head_body_file_and_labels(tmp_path):
    body = tmp_path / "summary.md"
    body.write_text("summary")
    stub = Stub({("pr", "create"): (0, "https://github.com/acme/report/pull/9\n", "")})
    pr = GitHubPullRequests("acme/report", stub).create(tmp_path, base="main", head="run-1", title="Fix", body_file=body, labels=["factory"])
    assert pr == PrRef(9, "https://github.com/acme/report/pull/9", "run-1", "main")
    call = stub.calls[0]
    assert call[call.index("--base") + 1] == "main" and call[call.index("--head") + 1] == "run-1"
    assert call[call.index("--body-file") + 1] == str(body) and "--label" in call


@pytest.mark.parametrize("state,want", [("OPEN", "open"), ("MERGED", "merged"), ("CLOSED", "closed")])
def test_pr_state_maps_github_states(state, want):
    out = json.dumps({"state": state, "mergeable": "MERGEABLE", "reviewDecision": "APPROVED", "statusCheckRollup": []})
    pr = GitHubPullRequests("a/b", Stub({("pr", "view"): (0, out, "")})).state(PrRef(1, "u", "h", "b"))
    assert pr.state == want and pr.review_decision == "APPROVED"


def test_pr_merge_is_auto_squash_and_deletes_the_branch_by_default():
    stub = Stub()
    GitHubPullRequests("a/b", stub).merge(PrRef(5, "u", "h", "b"))
    call = stub.calls[0]
    assert call[:3] == ["pr", "merge", "5"] and "--squash" in call and "--auto" in call and "--delete-branch" in call


def test_pr_merge_refuses_an_unknown_method():
    with pytest.raises(FactoryError, match="unknown merge method"):
        GitHubPullRequests("a/b", Stub()).merge(PrRef(5, "u", "h", "b"), method="octopus")


def test_request_reviewers_adds_them_and_does_nothing_for_an_empty_list():
    stub = Stub()
    prs = GitHubPullRequests("a/b", stub)
    prs.request_reviewers(PrRef(5, "u", "h", "b"), ["bob", "carol"])
    prs.request_reviewers(PrRef(5, "u", "h", "b"), [])
    assert len(stub.calls) == 1 and stub.calls[0][stub.calls[0].index("--add-reviewer") + 1] == "bob,carol"


def test_comment_posts_the_body_on_the_pull_request():
    stub = Stub()
    GitHubPullRequests("a/b", stub).comment(PrRef(5, "u", "h", "b"), "Merge check with CI green: Human review: x")
    (call,) = stub.calls
    assert call[:3] == ["pr", "comment", "5"] and call[call.index("--body") + 1].startswith("Merge check")
    assert call[call.index("-R") + 1] == "a/b"


# --- CI mapping (entry shape ASSUMED from GitHub's documented fields) ---

def entry(name, status="COMPLETED", conclusion="SUCCESS"):
    return {"name": name, "status": status, "conclusion": conclusion}


def test_ci_green_red_pending():
    assert ci_from_rollup([entry("a"), entry("b", conclusion="SKIPPED")])[0] == "green"
    assert ci_from_rollup([entry("a"), entry("b", conclusion="FAILURE")])[0] == "red"
    assert ci_from_rollup([entry("a"), entry("b", status="IN_PROGRESS", conclusion="")])[0] == "pending"


def test_an_empty_rollup_is_pending_not_green():
    assert ci_from_rollup([])[0] == "pending"


def test_an_unrecognised_result_is_never_green():
    assert ci_from_rollup([entry("a", conclusion="SOMETHING_NEW")])[0] == "pending"


def test_a_failure_wins_over_pending():
    assert ci_from_rollup([entry("a", status="IN_PROGRESS", conclusion=""), entry("b", conclusion="TIMED_OUT")])[0] == "red"


def test_checks_output_lists_each_check():
    ci, tail = ci_from_rollup([entry("build"), entry("test", conclusion="FAILURE")])
    assert "build: SUCCESS" in tail and "test: FAILURE" in tail


# --- errors ---

def test_an_expired_login_needs_a_human_with_the_gh_auth_hint():
    stub = Stub({("issue", "list"): (1, "", "To get started with GitHub CLI, please run:  gh auth login")})
    with pytest.raises(FactoryError) as e:
        GitHubTracker("a/b", stub).list_new(None)
    assert e.value.code == "git.auth_expired" and e.value.kind == "human" and "gh auth login" in e.value.hint


def test_a_network_error_is_transient():
    stub = Stub({("issue", "list"): (1, "", "error connecting to api.github.com: connection reset")})
    with pytest.raises(FactoryError) as e:
        GitHubTracker("a/b", stub).list_new(None)
    assert e.value.code == "git.network" and e.value.kind == "transient"


def test_an_unrecognised_gh_failure_is_not_hidden_under_another_code():
    stub = Stub({("issue", "list"): (1, "", "something unexpected")})
    with pytest.raises(FactoryError) as e:
        GitHubTracker("a/b", stub).list_new(None)
    assert e.value.code == "git.command_failed"


# --- the file tracker makes no GitHub call ---

def test_the_file_tracker_reads_markdown_front_matter_and_makes_no_github_call(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a) or (_ for _ in ()).throw(AssertionError("a process was run")))
    (tmp_path / "add-export.md").write_text("---\ntitle: Add CSV export\nlabels: [feature, ui]\n---\nUsers want CSV.\n")
    t = FileTracker(tmp_path)
    [src] = t.list_new(None)
    assert (src.type, src.ref, src.title, src.labels, src.body) == ("markdown", "add-export.md", "Add CSV export", ["feature", "ui"], "Users want CSV.")
    t.set_status(src.ref, "factory:running")
    t.ensure_labels(["factory"])
    assert called == []


def test_a_missing_request_file_is_reported(tmp_path):
    with pytest.raises(FactoryError, match="no request file"):
        FileTracker(tmp_path).fetch("nope.md")


def test_current_user_reads_the_login_gh_is_signed_in_as():
    stub = Stub({("api", "user"): (0, "plaktoz\n", "")})
    assert GitHubPullRequests("a/b", stub).current_user() == "plaktoz"
    assert stub.calls[0] == ["api", "user", "-q", ".login"]


def test_current_user_is_refused_when_gh_gives_no_login():
    stub = Stub({("api", "user"): (1, "", "HTTP 401")})
    with pytest.raises(FactoryError):
        GitHubPullRequests("a/b", stub).current_user()
