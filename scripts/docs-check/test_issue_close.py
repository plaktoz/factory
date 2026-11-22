"""issue_close.py: a merged pull request whose title names an open issue is a problem. Run: python3 -m pytest scripts/docs-check/test_issue_close.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue_close  # noqa: E402
from issue_close import open_issue_problems  # noqa: E402


def pr(number, title, merged="2026-11-22T00:22:26Z"):
    return {"number": number, "title": title, "mergedAt": merged}


def test_a_merged_pr_whose_title_names_an_open_issue_is_reported_with_the_fix():
    problems = open_issue_problems([pr(96, "gc frees worktrees (pilot #86)")], {86})
    assert len(problems) == 1 and "PR #96" in problems[0] and "#86" in problems[0] and "Refs #86" in problems[0]


def test_a_closed_issue_is_not_reported():
    assert open_issue_problems([pr(99, "Stop a task after crashes (#87)")], {12}) == []


def test_an_issue_named_only_in_the_body_is_not_read():
    # the body of PR 96 names #87, which it only touched; the check reads titles, so it has nothing to see
    assert open_issue_problems([pr(96, "gc frees worktrees")], {87}) == []


def test_a_pr_merged_before_the_rule_is_exempt():
    assert open_issue_problems([pr(71, "Stream logs (#56)", merged="2026-11-21T10:57:00Z")], {56}) == []


def test_two_issues_in_one_title_are_each_reported_once():
    problems = open_issue_problems([pr(5, "Fix #3, #4 and #3 again")], {3, 4})
    assert [("#3" in p, "#4" in p) for p in problems] == [(True, False), (False, True)]


def test_fetch_returns_none_when_gh_cannot_answer(monkeypatch):
    monkeypatch.setattr(issue_close, "_gh", lambda args, cwd: None)
    assert issue_close.fetch(".") is None


def test_fetch_pairs_the_merged_prs_with_the_open_issue_numbers(monkeypatch):
    answers = {"pr": [pr(1, "x (#2)")], "issue": [{"number": 2}, {"number": 9}]}
    monkeypatch.setattr(issue_close, "_gh", lambda args, cwd: answers[args[0]])
    assert issue_close.fetch(".") == ([pr(1, "x (#2)")], {2, 9})
