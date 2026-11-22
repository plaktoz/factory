"""Run from the repo root: python3 -I -m pytest scripts/test_spec_pilot.py (or with uv: uv run --with pytest ...)."""
import importlib.util
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location("spec_pilot", Path(__file__).with_name("spec-pilot.py"))
sp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)
Row = sp.Row


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def _merge(repo, branch, files):
    _git(repo, "checkout", "-q", "-b", branch)
    for name, text in files.items():
        (repo / name).write_text(text)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", branch)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", branch, "-m", f"merge {branch}")
    return _git(repo, "rev-parse", "HEAD")


def test_rework_counts_only_the_pull_requests_own_lines_that_a_later_commit_rewrites(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "factory").mkdir()
    (repo / "factory/x.py").write_text("a\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    first = _merge(repo, "p1", {"factory/x.py": "a\nb1\nb2\nb3\nb4\n"})
    second = _merge(repo, "p2", {"factory/y.py": "z1\nz2\n"})
    (repo / "factory/x.py").write_text("a\nb1\nb2-fixed\nb3\nb4\n")
    _git(repo, "commit", "-q", "-am", "fix")
    end = _git(repo, "rev-parse", "HEAD")
    monkeypatch.chdir(repo)
    assert sp.rework(first, end) == (4, 1)
    assert sp.rework(second, end) == (2, 0)
    assert sp.rework(first, first) == (4, 0)


def _rows(rates, group="baseline"):
    return [Row(i, group, 1 if group == "spec" else None, "", 100, round(r * 100), r) for i, r in enumerate(rates)]


def test_a_window_where_most_baselines_show_no_rework_is_inconclusive():
    verdict = sp.summary(_rows([0, 0, 0, 0, 0, 0, 0.1, 0.2, 0.05]) + _rows([0], "spec"))
    assert verdict.startswith("inconclusive") and "67% of 9" in verdict


def test_a_spec_rate_inside_the_baseline_range_is_no_evidence():
    verdict = sp.summary(_rows([0.05, 0.1, 0.15, 0.2]) + _rows([0.1], "spec"))
    assert verdict.startswith("no evidence either way")


def test_a_spec_rate_above_or_below_the_baseline_range_is_reported():
    base = _rows([0.05, 0.1, 0.15, 0.2])
    assert "[0.9]" in sp.summary(base + _rows([0.9], "spec"))
    assert "[0.0]" in sp.summary(base + _rows([0.0], "spec"))


def test_no_spec_pull_request_with_a_full_window_is_inconclusive_never_zero():
    assert sp.summary(_rows([0.05, 0.1])).startswith("inconclusive: a group has no PR")


def test_a_spec_pull_request_is_one_that_closes_the_issue_or_names_it_in_its_title():
    specs = {86, 103}
    def pr(title, body="", closes=()):
        return {"title": title, "body": body, "closingIssuesReferences": [{"number": n} for n in closes]}
    assert sp.issue_of(pr("gc frees worktrees (pilot #86)"), specs) == 86
    assert sp.issue_of(pr("Make the lock work on Windows (issue 103)"), specs) == 103
    assert sp.issue_of(pr("Stop a task", closes=[86]), specs) == 86
    assert sp.issue_of(pr("Record the decisions", body="opened #86 as a pilot ticket"), specs) is None


def test_a_window_is_a_number_with_a_unit_and_nothing_else():
    assert sp.parse_window("30s") == 30
    assert sp.parse_window("5m") == 300
    assert sp.parse_window("2h") == 7200
    assert sp.parse_window("1.5h") == 5400
    assert sp.parse_window("3d") == 259200
    for bad in ("", "5", "h", "5x", "0m", "-5m", "5 m"):
        try:
            sp.parse_window(bad)
        except Exception:
            continue
        raise AssertionError(f"{bad!r} was accepted")


def test_a_window_is_labelled_in_its_own_unit():
    assert [sp.label(s) for s in (30, 300, 7200, 259200, 90)] == ["30s", "5m", "2h", "3d", "90s"]


def test_a_pull_request_titled_as_a_follow_up_to_an_issue_is_not_a_spec_pull_request():
    specs = {103}
    assert sp.issue_of({"title": "Fix a follow-up (issue 103 follow-up)", "body": "", "closingIssuesReferences": []}, specs) is None
    assert sp.issue_of({"title": "Fix the lock (issue 103)", "body": "", "closingIssuesReferences": []}, specs) == 103


def test_a_file_moved_on_main_is_followed_and_a_deleted_file_counts_as_reworked(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "factory").mkdir()
    (repo / "factory/x.py").write_text("a\nb\nc\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    merge = _merge(repo, "p1", {"factory/x.py": "a\nb\nc\nd\n"})  # the PR adds one line, d
    _git(repo, "mv", "factory/x.py", "factory/y.py")
    _git(repo, "commit", "-q", "-m", "move")
    _git(repo, "mv", "factory/y.py", "factory/z.py")
    _git(repo, "commit", "-q", "-m", "move again")
    end = _git(repo, "rev-parse", "HEAD")
    monkeypatch.chdir(repo)
    assert sp.rework(merge, end) == (1, 0)
    _git(repo, "rm", "-q", "factory/z.py")
    _git(repo, "commit", "-q", "-m", "delete")
    gone = _git(repo, "rev-parse", "HEAD")
    assert sp.rework(merge, gone) == (1, 1)

