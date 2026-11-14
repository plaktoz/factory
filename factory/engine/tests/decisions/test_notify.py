"""Module 11 acceptance criteria, notify half: attention items, GitHub and markdown channels, reminders, and a
failed webhook never stopping the run."""

import pytest
import yaml

from factory_engine import decisions as D
from factory_engine import notify as N
from factory_engine import state
from factory_engine.adapters.tracker.fake import FakeTracker
from factory_engine.config import Config
from factory_engine.types import AttentionItem, StageState

from conftest import architect_packet, make_request, set_run

NOW = "2026-11-15T10:00:00+08:00"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """A channel is retried with a pause. A test never waits for it."""
    monkeypatch.setattr(N.time, "sleep", lambda s: None)


class DownTracker(FakeTracker):
    """A tracker that fails every call, not only the next one."""

    def set_status(self, ref, status, *, comment=None, link=None):
        raise OSError("gh is down")


def cfg(notify=None, dashboard_url=None):
    machine = {"max_workers": 6}
    if dashboard_url:
        machine["dashboard_url"] = dashboard_url
    repo = {"notify": notify if notify is not None else {"github_mention": "author", "desktop": False,
                                                         "webhook": None, "remind_after_hours": 24}}
    return Config(machine=machine, repo=repo)


def ask_architecture(run, packet=None):
    D.request(run.run_dir, "architecture", 1, kind="decision", packet=packet or architect_packet())
    return set_run(run, status="awaiting_approval", stage="architecture")


def attention(run, now=NOW):
    return N.attention_for(state.read_run(run.run_dir), now=now)


# --- attention_for ---

def test_an_architecture_stop_raises_a_decision_item_with_page_and_command(run):
    ask_architecture(run)
    item = attention(run)
    assert item.kind == "decision" and item.stage == "architecture"
    assert item.page.name == "architecture.1.html" and item.page.is_file()
    sha = D.read_decision(run.run_dir, "architecture", 1)["packet"]["sha"]
    assert item.command == f"factory decide new-color-q1w2e --stage architecture --packet {sha} D1=opt-a D2=opt-a"
    assert item.summary.startswith("Frontend stack:")


def test_an_approval_stop_raises_an_approval_item(run):
    D.request(run.run_dir, "propose", 1, kind="approval")
    set_run(run, status="awaiting_approval", stage="propose")
    assert attention(run).kind == "approval"


def test_a_blocked_run_raises_a_blocked_item(run):
    set_run(run, status="blocked", stage="verify", stages=[StageState("verify", 1, "failed", [], "t0", "t1")])
    item = attention(run)
    assert item.kind == "blocked" and item.command == "factory retry new-color-q1w2e"


def test_a_running_run_raises_nothing(run):
    set_run(run, status="running", stage="fix", stages=[StageState("fix", 1, "running", [], "t0", None)])
    assert attention(run) is None


def test_the_since_time_is_kept_while_the_same_item_stays_open(run):
    ask_architecture(run)
    first = attention(run, now="2026-11-15T10:00:00+08:00")
    set_run(run, status="awaiting_approval", stage="architecture", attention=first)
    again = attention(run, now="2026-11-16T09:00:00+08:00")
    assert again.since == first.since == "2026-11-15T10:00:00+08:00"


def test_an_item_for_a_run_without_a_decision_file_and_no_pr_is_none(run):
    set_run(run, status="awaiting_approval", stage="architecture")
    assert attention(run) is None


def test_a_merge_review_stop_with_no_decision_file_raises_a_merge_review_item(run):
    """Merge review is answered on GitHub, so it has no decision file; the item links to the pull request."""
    from factory_engine.types import PrRef
    pr = PrRef(number=7, url="https://github.com/acme/report/pull/7", head="new-color-q1w2e", base="main")
    set_run(run, status="awaiting_approval", stage="merge", pr=pr)
    item = attention(run)
    assert item.kind == "merge_review" and item.page is None and item.command is None
    assert "https://github.com/acme/report/pull/7" in item.summary


def test_a_request_changed_item_is_passed_through_while_the_run_runs(run):
    """Module 4 raises request_changed when a GitHub issue body changes; attention_for keeps it on the run."""
    from factory_engine.types import AttentionItem
    changed = AttentionItem(kind="request_changed", run_id="new-color-q1w2e", stage="fix", since=NOW,
                            summary="The issue body changed", page=None, command=None)
    set_run(run, status="running", stage="fix", stages=[StageState("fix", 1, "running", [], "t0", None)],
            attention=changed)
    assert attention(run) == changed


# --- channels: GitHub request ---

def test_a_github_request_gets_the_needs_human_label_and_a_comment_with_link_and_path(run):
    ask_architecture(run)
    tracker = FakeTracker()
    report = N.notify(attention(run), cfg(dashboard_url="http://127.0.0.1:9000"), tracker)
    assert "tracker" in report.sent
    call = tracker.statuses[-1]
    assert call.status == "factory:needs-human" and call.ref == "acme/report#42"
    assert "@alice" in call.comment
    assert "decisions/architecture.1.yaml" in call.comment
    assert "factory decide new-color-q1w2e" in call.comment


def test_the_tracker_comment_carries_the_dashboard_link_on_every_status_change(run):
    ask_architecture(run)
    tracker = FakeTracker()
    seen = {}

    original = tracker.set_status

    def spy(ref, status, *, comment=None, link=None):
        seen.update(link=link, comment=comment)
        return original(ref, status, comment=comment, link=link)
    tracker.set_status = spy
    N.notify(attention(run), cfg(dashboard_url="http://127.0.0.1:9000/"), tracker)
    assert seen["comment"] and "Dashboard: http://127.0.0.1:9000/runs/new-color-q1w2e/decisions/architecture.1.html" in seen["comment"]


def test_a_blocked_github_run_gets_the_blocked_label(run):
    set_run(run, status="blocked", stage="verify", stages=[StageState("verify", 1, "failed", [], "t0", "t1")])
    tracker = FakeTracker()
    N.notify(attention(run), cfg(), tracker)
    assert tracker.statuses[-1].status == "factory:blocked"


def test_no_mention_when_the_config_says_not_to(run):
    ask_architecture(run)
    tracker = FakeTracker()
    N.notify(attention(run), cfg({"github_mention": "none", "desktop": False, "webhook": None}), tracker)
    assert "@alice" not in tracker.statuses[-1].comment


# --- channels: markdown request ---

def markdown_run(home, tmp_path):
    from factory_engine import state as S
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    req_file = inbox / "new-color.md"
    req_file.write_text("---\ntitle: New color\n---\nAdd a color.\n")
    ref = S.init_run(home, tmp_path / "repo", "local/repo", "new-color-q1w2e",
                     make_request("markdown", "new-color.md", author=None, files=[req_file]),
                     branch="new-color-q1w2e", worktree=tmp_path / "wt", kit_hash="ab12")
    return ref, req_file


def test_a_markdown_request_gets_factory_status_and_attention_in_front_matter(home, tmp_path):
    ref, req_file = markdown_run(home, tmp_path)
    ask_architecture(ref)
    report = N.notify(attention(ref), cfg(), FakeTracker())
    assert "front_matter" in report.sent
    text = req_file.read_text()
    front = yaml.safe_load(text.split("---\n", 2)[1])
    assert front["factory_status"] == "needs-human"
    assert front["title"] == "New color"
    assert front["factory_attention"].startswith("Frontend stack:")
    assert text.endswith("Add a color.\n")


def test_rewriting_front_matter_keeps_one_copy_of_each_key(home, tmp_path):
    ref, req_file = markdown_run(home, tmp_path)
    ask_architecture(ref)
    N.notify(attention(ref), cfg(), FakeTracker())
    N.notify(attention(ref), cfg(), FakeTracker())
    text = req_file.read_text()
    assert text.count("factory_status:") == 1 and text.count("factory_attention:") == 1


# --- channels: desktop and webhook, retried and never fatal ---

def test_a_failed_webhook_retries_then_reports_and_the_run_is_untouched(run, monkeypatch):
    ask_architecture(run)
    calls = []

    def down(url, payload):
        calls.append(url)
        raise OSError("connection refused")
    monkeypatch.setattr(N, "_post", down)
    before = state.read_run(run.run_dir).status
    report = N.notify(attention(run), cfg({"github_mention": "author", "desktop": False,
                                           "webhook": "https://hooks.example/x"}), FakeTracker())
    assert len(calls) == 3
    assert "connection refused" in report.failed["webhook"]
    assert state.read_run(run.run_dir).status == before
    assert "webhook" not in report.sent


def test_a_webhook_that_recovers_on_the_second_try_counts_as_sent(run, monkeypatch):
    ask_architecture(run)
    tries = []

    def flaky(url, payload):
        tries.append(1)
        if len(tries) < 2:
            raise OSError("timeout")
    monkeypatch.setattr(N, "_post", flaky)
    report = N.notify(attention(run), cfg({"github_mention": "author", "desktop": False,
                                           "webhook": "https://hooks.example/x"}), FakeTracker())
    assert "webhook" in report.sent and not report.failed


def test_a_tracker_that_is_down_is_reported_and_never_raises(run):
    ask_architecture(run)
    report = N.notify(attention(run), cfg(), DownTracker())
    assert "gh is down" in report.failed["tracker"] and "tracker" not in report.sent


def test_a_tracker_failure_that_clears_on_retry_counts_as_sent(run):
    ask_architecture(run)
    tracker = FakeTracker()
    tracker.fail_next = OSError("rate limited")
    report = N.notify(attention(run), cfg(), tracker)
    assert "tracker" in report.sent and not report.failed
    assert tracker.statuses[-1].status == "factory:needs-human"


def test_a_failed_desktop_notification_never_raises(run, monkeypatch):
    ask_architecture(run)

    def no_tool(*a, **k):
        raise FileNotFoundError("osascript")
    monkeypatch.setattr(N, "_desktop", no_tool)
    report = N.notify(attention(run), cfg({"github_mention": "author", "desktop": True, "webhook": None}), FakeTracker())
    assert "desktop" in report.failed


def test_each_notification_is_recorded_as_an_event(run):
    ask_architecture(run)
    N.notify(attention(run), cfg(), FakeTracker())
    sent = [e for e in state.read_events(run.run_dir) if e.type == "attention_notified"]
    assert len(sent) == 1 and sent[0].data["kind"] == "decision"


# --- reminders ---

def item(since, run_id="new-color-q1w2e", stage="architecture"):
    return AttentionItem(kind="decision", run_id=run_id, stage=stage, since=since, summary="s", page=None, command=None)


def test_reminders_fire_after_remind_after_hours(run):
    ask_architecture(run)
    old = item("2026-11-14T09:00:00+08:00")
    fresh = item("2026-11-15T09:30:00+08:00")
    due = N.due_reminders([old, fresh], cfg(), now=NOW)
    assert due == [old]


def test_a_reminder_is_counted_from_the_last_notification_not_the_first(run):
    ask_architecture(run)
    old = item("2026-11-14T09:00:00+08:00")
    state.append_event(run.run_dir, "attention_notified", kind="decision", stage="architecture", sent=[], failed={})
    assert N.due_reminders([old], cfg(), now=NOW) == []


def test_reminders_can_be_turned_off_with_zero_hours(run):
    old = item("2026-01-01T00:00:00+00:00")
    assert N.due_reminders([old], cfg({"github_mention": "author", "desktop": False, "webhook": None,
                                       "remind_after_hours": 0}), now=NOW) == []


def test_reminders_compare_a_naive_time_as_utc(run):
    old = item("2026-11-14T00:00:00")
    assert N.due_reminders([old], cfg(), now="2026-11-15T12:00:00+00:00") == [old]


def test_no_network_call_is_made_while_notifying_a_markdown_request(home, tmp_path, monkeypatch):
    ref, _ = markdown_run(home, tmp_path)
    ask_architecture(ref)
    monkeypatch.setattr(N, "_post", lambda *a: pytest.fail("no webhook is configured"))
    N.notify(attention(ref), cfg(), FakeTracker())
