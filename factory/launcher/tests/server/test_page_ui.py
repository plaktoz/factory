"""Module 15, the page criteria that need a browser: the poll, Show JSON, Needs you, run detail and copy.

Each test loads the real factory/dashboard/index.html in headless Chrome (page_harness.run_page). The server's JSON
comes from App.handle, so the page gets real server output. The page's own timer, buttons and clipboard code run.
Skipped when Google Chrome is not installed."""

import json
import shutil

import pytest

from factory_engine import state
from factory_engine.lock import acquire_lock, release
from factory_engine.types import TaskState
from page_harness import CHROME, click, run_page, set_body, snap
from helpers import TOKEN, approval_page, attention_for, call, make_repo, make_run, set_run

pytestmark = pytest.mark.skipif(not CHROME.exists(), reason="Google Chrome is not installed")

STATE = "/api/state.json"
ROWS = ("function(){return Array.prototype.map.call(document.querySelectorAll('#runs tr.run'),"
        "function(r){return r.getAttribute('data-run');});}")
NEEDS_IDS = ("function(){return Array.prototype.map.call(document.querySelectorAll('#needs a.open-run'),"
             "function(a){return a.getAttribute('data-run');});}")
NEEDS_OPEN = ("function(){return Array.prototype.map.call(document.querySelectorAll('#needs a[target=\"_blank\"]'),"
              "function(a){return {href:a.getAttribute('href'),label:a.textContent.trim()};});}")
NEEDS_COPY_LABELS = ("function(){return Array.prototype.map.call(document.querySelectorAll('#needs .needs-item button.copy'),"
                     "function(b){return b.textContent.trim();});}")
JSON_SHOWN = "function(){return !document.getElementById('json-section').classList.contains('hidden');}"
JSON_TEXT = "function(){return document.getElementById('json').textContent;}"
DETAIL_TITLE = "function(){return document.getElementById('detail-title').textContent;}"


def _body(app) -> str:
    return call(app, "GET", STATE).body.decode()


def _ids(body: str) -> list[str]:
    return [r["run_id"] for r in json.loads(body)["runs"] if not r["hidden"]]


def _task(run_dir, task_id, worktree):
    lock = acquire_lock(run_dir, "engine")
    try:
        state.write_task(run_dir, TaskState(task_id=task_id, stage="fix", status="running", attempt=1, restarts=0,
                                            task_base=None, worktree=worktree, checkpoints=0), lock=lock)
    finally:
        release(lock)


# --- criterion: a new run appears within one refresh with no API call; an archived run disappears ---

def test_a_new_run_appears_on_the_next_refresh_and_an_archived_run_disappears(home, app, tmp_path):
    ref_a = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    before = _body(app)
    make_run(home, make_repo(tmp_path, "portal"), key="github.com/acme/portal", run_id="fix-b-bbbbb")
    shutil.rmtree(ref_a.run_dir)  # what housekeeping does when it archives a run
    after = _body(app)
    assert _ids(before) == ["fix-a-aaaaa"] and _ids(after) == ["fix-b-bbbbb"]

    result = run_page(tmp_path, {STATE: before}, [
        (1000, snap("early", ROWS)),
        (2000, set_body(STATE, after)),  # the server's next answer changes; the page has not asked again yet
        (4000, snap("before_poll", ROWS)),
        (5500, snap("after_poll", ROWS)),  # the page's 5 s poll has run once since the change
    ], token=TOKEN)
    assert result["errors"] == []
    assert result["snaps"]["early"] == ["fix-a-aaaaa"]
    assert result["snaps"]["before_poll"] == ["fix-a-aaaaa"]
    assert result["snaps"]["after_poll"] == ["fix-b-bbbbb"]


# --- criterion: the page refreshes every 5 seconds without a manual click ---

def test_the_page_polls_the_state_every_five_seconds_without_a_click(home, app, tmp_path):
    make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    result = run_page(tmp_path, {STATE: _body(app)}, [], token=TOKEN)  # no steps: nobody clicks anything
    assert result["errors"] == []
    polls = [f for f in result["fetches"] if f["path"] == STATE]
    assert len(polls) >= 3  # at load, at 5 s, at 10 s
    assert all(f["method"] == "GET" and f["token"] == TOKEN for f in polls)
    gaps = [b["at"] - a["at"] for a, b in zip(polls, polls[1:])]
    assert all(abs(gap - 5000) < 50 for gap in gaps), gaps


# --- criterion: Show JSON displays the document in use ---

def test_show_json_displays_the_document_in_use(home, app, tmp_path):
    make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    before = _body(app)
    make_run(home, make_repo(tmp_path, "portal"), key="github.com/acme/portal", run_id="fix-b-bbbbb")
    after = _body(app)

    result = run_page(tmp_path, {STATE: before}, [
        (1000, click("#show-json")),
        (1200, snap("shown", JSON_SHOWN)),
        (1200, snap("json", JSON_TEXT)),
        (2000, set_body(STATE, after)),
        (5500, snap("json_after_poll", JSON_TEXT)),
        (6000, click("#show-json")),
        (6200, snap("hidden_again", JSON_SHOWN)),
    ], token=TOKEN)
    assert result["errors"] == []
    assert result["snaps"]["shown"] is True
    assert json.loads(result["snaps"]["json"]) == json.loads(before)
    assert json.loads(result["snaps"]["json_after_poll"]) == json.loads(after)
    assert result["snaps"]["hidden_again"] is False


# --- criterion: run detail shows repo, worktree, task worktrees, branch and source paths, each copyable ---

def test_run_detail_copy_buttons_copy_each_path(home, app, tmp_path):
    ref = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-login-a1b2c")
    _task(ref.run_dir, "backend", tmp_path / "wt-backend")
    _task(ref.run_dir, "tests", tmp_path / "wt-tests")
    detail_body = call(app, "GET", "/api/runs/fix-login-a1b2c").body.decode()
    paths = json.loads(detail_body)["paths"]
    labels = {p["label"] for p in paths}  # the server also lists the run folder; the five named paths must be there
    assert {"Repo", "Worktree", "Task backend worktree", "Task tests worktree", "Branch", "Source"} <= labels

    steps = [(1000, click("tr.run", None, 0))]
    steps += [(2000, click("#detail-body button.copy", None, i)) for i in range(len(paths))]
    steps.append((2500, snap("title", DETAIL_TITLE)))
    result = run_page(tmp_path, {STATE: _body(app), "/api/runs/fix-login-a1b2c": detail_body}, steps, token=TOKEN)
    assert result["errors"] == []
    assert result["snaps"]["title"] == "fix-login-a1b2c"
    assert result["clipboard"] == [p["value"] for p in paths]


# --- criterion: Needs you lists every attention item, with Open page and Copy path for decisions ---

def test_needs_you_lists_every_item_with_open_page_and_copy_path(home, app, tmp_path, held):
    a = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    b = make_run(home, make_repo(tmp_path, "portal"), key="github.com/acme/portal", run_id="gather-b-bbbbb")
    set_run(a, held, status="awaiting_approval", stage="propose",
            attention=attention_for(a, page=approval_page(a), since="2026-11-15T10:00:00+00:00"))
    set_run(b, held, status="awaiting_approval", stage="propose",
            attention=attention_for(b, page=approval_page(b), since="2026-11-15T09:00:00+00:00"))
    body = _body(app)
    items = json.loads(body)["attention"]
    assert [i["run_id"] for i in items] == ["gather-b-bbbbb", "fix-a-aaaaa"]

    result = run_page(tmp_path, {STATE: body}, [
        (1000, click("#needs .needs-item button.copy", None, 0)),
        (1100, click("#needs .needs-item button.copy", None, 1)),
        (1500, snap("ids", NEEDS_IDS)),
        (1500, snap("open", NEEDS_OPEN)),
    ], token=TOKEN)
    assert result["errors"] == []
    assert result["snaps"]["ids"] == ["gather-b-bbbbb", "fix-a-aaaaa"]
    assert result["clipboard"] == [i["page_path"] for i in items]
    assert result["snaps"]["open"] == [{"href": i["page_url"] + "?token=" + TOKEN, "label": "Open page"} for i in items]
    for i in items:  # the Open page link is a real page on the server, reached with the token in its URL
        resp = call(app, "GET", i["page_url"] + "?token=" + TOKEN, token=None)
        assert resp.status == 200 and b"<html" in resp.body


# --- defect: after a copy the button must go back to its own label, not to a generic "Copy" ---

def test_a_copy_button_goes_back_to_its_own_label_after_it_copies(home, app, tmp_path, held):
    a = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    set_run(a, held, status="awaiting_approval", stage="propose",
            attention=attention_for(a, page=approval_page(a), since="2026-11-15T10:00:00+00:00"))
    result = run_page(tmp_path, {STATE: _body(app)}, [
        (1000, click("#needs .needs-item button.copy", None, 0)),
        (1100, click("#needs .needs-item button.copy", None, 0)),  # a second click before the first reset
        (1500, snap("during", NEEDS_COPY_LABELS)),
        (3000, snap("after", NEEDS_COPY_LABELS)),
    ], token=TOKEN)
    assert result["errors"] == []
    assert result["snaps"]["during"] == ["Copied"]
    assert result["snaps"]["after"] == ["Copy path"]


# --- a state request that fails or hangs (owner decision, 2026-11-24): keep the old rows, warn, give up after 10 s ---

BANNER = ("function(){var b=document.getElementById('error');"
          "return {shown:!b.classList.contains('hidden'),text:b.textContent};}")


def test_a_state_request_that_hangs_gives_up_after_ten_seconds_and_keeps_the_rows(home, app, tmp_path):
    """The load's request answers, so rows are drawn. From 100 ms every request hangs. The refresh at 5 s is given up
    10 s after it started, at 15 s: the warning is off before that and on after it, and the rows stay throughout."""
    from page_harness import hang
    make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    steps = [(100, hang(STATE)), (14000, snap("before", BANNER)), (16000, snap("after", BANNER)),
             (16000, snap("rows", ROWS))]
    result = run_page(tmp_path, {STATE: _body(app)}, steps, token=TOKEN, budget_ms=18000)
    assert result["errors"] == []
    assert result["snaps"]["before"]["shown"] is False, "no warning while the refresh is still within its 10 s"
    assert result["snaps"]["after"]["shown"] is True, "the warning shows once the refresh gives up"
    assert "10" in result["snaps"]["after"]["text"]
    assert result["snaps"]["rows"] == ["fix-a-aaaaa"], "the last rows stay on screen under the warning"
