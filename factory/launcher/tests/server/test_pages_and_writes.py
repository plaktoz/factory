"""Module 15: the decision page served with a CSP and the token injected, the write routes through the launcher,
bad input as HTTP 400, and the placeholder dashboard page."""

import json
from pathlib import Path

from factory_engine import state, usage
from factory_launcher.server import app as app_module

from helpers import (HOST, ORIGIN, TOKEN, FakeLauncher, approval_page, attention_for, call, get_json, make_repo,
                       make_run, set_run)


def _ready(home, tmp_path, held):
    ref = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    page = approval_page(ref)
    set_run(ref, held, status="awaiting_approval", stage="propose", attention=attention_for(ref, page=page))
    return ref, page


# --- decision page: served as is, with a CSP header and the token injected at serve time only ---

def test_the_decision_page_is_served_with_a_csp_header(app, home, tmp_path, held):
    ref, page = _ready(home, tmp_path, held)
    resp = app.handle("GET", f"/runs/fix-a-aaaaa/decisions/propose.1.html?token={TOKEN}", {"Host": HOST}, b"")
    assert resp.status == 200 and resp.content_type.startswith("text/html")
    csp = resp.headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "form-action 'none'" in csp
    assert "unsafe-eval" not in csp


def test_the_token_is_injected_into_the_served_page_but_not_saved_to_disk(app, home, tmp_path, held):
    ref, page = _ready(home, tmp_path, held)
    on_disk = page.read_bytes()
    resp = app.handle("GET", f"/runs/fix-a-aaaaa/decisions/propose.1.html?token={TOKEN}", {"Host": HOST}, b"")
    assert f"window.FACTORY_TOKEN={json.dumps(TOKEN)}".encode() in resp.body
    assert TOKEN.encode() not in on_disk
    assert page.read_bytes() == on_disk  # the file on disk is not rewritten


def test_the_served_page_still_shows_the_command_when_opened_from_disk(app, home, tmp_path, held):
    ref, page = _ready(home, tmp_path, held)
    resp = app.handle("GET", f"/runs/fix-a-aaaaa/decisions/propose.1.html?token={TOKEN}", {"Host": HOST}, b"")
    assert b'id="cmd"' in resp.body and b"factory" in resp.body


def test_a_decision_page_request_with_a_bad_name_is_not_found(app, home, tmp_path, held):
    _ready(home, tmp_path, held)
    resp = app.handle("GET", f"/runs/fix-a-aaaaa/decisions/..%2Fsecret.html?token={TOKEN}", {"Host": HOST}, b"")
    assert resp.status == 404


# --- writes: each goes through the launcher as a separate command, and the CLI's JSON is returned ---

def test_decide_builds_the_factory_decide_command_with_the_packet_hash(app, home, tmp_path, held, launcher):
    _ready(home, tmp_path, held)
    resp = call(app, "POST", "/api/runs/fix-a-aaaaa/decide", origin=ORIGIN, body={
        "packet": "661cb74d", "choices": {"D1": "opt-a"}, "notes": "Keep it simple", "by": "me"})
    assert resp.status == 200
    assert launcher.calls == [["decide", "fix-a-aaaaa", "--packet", "661cb74d", "D1=opt-a",
                               "--notes", "Keep it simple", "--by", "me", "--json"]]


def test_decide_passes_questions_as_separate_arguments(app, home, tmp_path, held, launcher):
    _ready(home, tmp_path, held)
    call(app, "POST", "/api/runs/fix-a-aaaaa/decide", origin=ORIGIN,
         body={"packet": "661cb74d", "questions": {"D2": "Can option B add charts later?"}})
    assert launcher.calls[0][:6] == ["decide", "fix-a-aaaaa", "--packet", "661cb74d",
                                     "--question", "D2=Can option B add charts later?"]


def test_a_failed_cli_call_returns_its_json_error_to_the_page(app, home, tmp_path, held):
    _ready(home, tmp_path, held)
    cli_error = {"ok": False, "code": "decision.stale_packet", "message": "packet changed",
                 "hint": "reopen the page", "data": {}}
    launcher = FakeLauncher(doc=cli_error, returncode=2)
    app.launcher = launcher
    resp = call(app, "POST", "/api/runs/fix-a-aaaaa/decide", origin=ORIGIN, body={"packet": "661cb74d"})
    assert resp.status == 422
    assert json.loads(resp.body) == cli_error


def test_a_launcher_that_prints_no_json_is_a_502_with_its_stderr(app, home, tmp_path, held):
    _ready(home, tmp_path, held)
    app.launcher = FakeLauncher(doc=None, returncode=1, stderr="boom")
    resp = call(app, "POST", "/api/runs/fix-a-aaaaa/retry", origin=ORIGIN, body={})
    assert resp.status == 502 and json.loads(resp.body)["message"] == "boom"


def test_note_queues_through_the_launcher_with_its_deny_globs(app, home, tmp_path, held, launcher):
    _ready(home, tmp_path, held)
    resp = call(app, "POST", "/api/runs/fix-a-aaaaa/note", origin=ORIGIN,
                body={"task": "backend", "text": "use the new client", "deny": ["src/legacy/**"]})
    assert resp.status == 200
    assert launcher.calls == [["note", "fix-a-aaaaa/backend", "use the new client", "--deny", "src/legacy/**", "--json"]]


def test_retry_goto_skip_and_abort_each_call_the_launcher(app, home, tmp_path, held, launcher):
    _ready(home, tmp_path, held)
    call(app, "POST", "/api/runs/fix-a-aaaaa/retry", origin=ORIGIN, body={})
    call(app, "POST", "/api/runs/fix-a-aaaaa/goto", origin=ORIGIN, body={"stage": "build"})
    call(app, "POST", "/api/runs/fix-a-aaaaa/skip", origin=ORIGIN, body={"gate": "tests", "reason": "flaky"})
    call(app, "POST", "/api/runs/fix-a-aaaaa/abort", origin=ORIGIN, body={"reason": "not needed"})
    assert launcher.calls == [
        ["retry", "fix-a-aaaaa", "--json"],
        ["goto", "fix-a-aaaaa", "build", "--json"],
        ["skip", "fix-a-aaaaa", "tests", "--reason", "flaky", "--json"],
        ["abort", "fix-a-aaaaa", "--reason", "not needed", "--json"],
    ]


# --- bad input is HTTP 400 with the reason, and nothing is sent to the launcher ---

def test_bad_input_is_400_with_the_reason_and_no_launcher_call(app, home, tmp_path, held, launcher):
    _ready(home, tmp_path, held)
    cases = [
        ("/api/runs/fix-a-aaaaa/decide", {"packet": "x; rm -rf /"}, "packet"),
        ("/api/runs/fix-a-aaaaa/decide", {"packet": "661cb74d", "choices": {"D1": "--evil"}}, "choice"),
        ("/api/runs/fix-a-aaaaa/note", {"task": "backend", "text": "--force"}, "text"),
        ("/api/runs/fix-a-aaaaa/note", {"task": "../x", "text": "hi"}, "task"),
        ("/api/runs/fix-a-aaaaa/goto", {}, "stage"),
        ("/api/runs/fix-a-aaaaa/skip", {"gate": "tests"}, "reason"),
        ("/api/runs/fix-a-aaaaa/abort", {"reason": "  "}, "reason"),
    ]
    for path, body, word in cases:
        resp = call(app, "POST", path, origin=ORIGIN, body=body)
        assert resp.status == 400, path
        assert word in json.loads(resp.body)["message"], (path, resp.body)
    assert launcher.calls == []


def test_a_body_that_is_not_json_is_400(app, home, tmp_path, held, launcher):
    _ready(home, tmp_path, held)
    resp = app.handle("POST", "/api/runs/fix-a-aaaaa/retry", {"Host": HOST, "Origin": ORIGIN,
                                                               "X-Factory-Token": TOKEN}, b"{not json")
    assert resp.status == 400 and launcher.calls == []


def test_a_write_to_an_unknown_run_is_404(app, home, tmp_path, launcher):
    make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    assert call(app, "POST", "/api/runs/nope-zzzzz/retry", origin=ORIGIN, body={}).status == 404
    assert launcher.calls == []


def test_a_get_on_a_write_route_is_405(app, home, tmp_path, held):
    _ready(home, tmp_path, held)
    assert call(app, "GET", "/api/runs/fix-a-aaaaa/retry").status == 405


# --- the placeholder page ---

def test_the_placeholder_page_is_the_static_index_with_a_csp(app):
    resp = app.handle("GET", "/", {"Host": HOST}, b"")
    assert resp.status == 200
    assert b"<title>Factory</title>" in resp.body
    assert b"window.FACTORY_TOKEN" not in resp.body  # the page takes the token from the URL at run time


def test_the_placeholder_page_has_a_csp_meta_tag_that_blocks_other_origins(app):
    body = app.handle("GET", "/", {"Host": HOST}, b"").body.decode()
    assert "Content-Security-Policy" in body and "default-src 'none'" in body


def test_the_placeholder_page_shows_each_required_control(app):
    body = app.handle("GET", "/", {"Host": HOST}, b"").body.decode()
    for needle in ('id="show-json"', 'id="needs"', 'id="counters"', "REFRESH_MS = 5000", 'data-copy', "Copy path"):
        assert needle in body, needle


# --- usage in run detail (phase 1a: read-only, per run) ---

def _two_attempts(home, tmp_path):
    ref = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    run = state.read_run(ref.run_dir)
    for task, tokens in (("be", (120, 30)), ("fe", (None, None))):
        n = usage.start_attempt(ref.run_dir, run, task, stage="fix", harness="claude", model_requested=None)
        usage.finish_attempt(ref.run_dir, task, n, exit="ok", input_tokens=tokens[0], output_tokens=tokens[1],
                             models=["claude-sonnet"])
    return ref


def test_run_detail_returns_token_totals_by_model_repo_and_day(app, home, tmp_path):
    _two_attempts(home, tmp_path)
    status, doc = get_json(app, "/api/runs/fix-a-aaaaa")
    assert status == 200
    totals = doc["usage"]["by_model"]["claude-sonnet"]
    assert (totals["attempts"], totals["input_tokens"], totals["output_tokens"], totals["total_tokens"]) == (2, 120, 30, 150)
    assert totals["attempts_without_count"] == 1  # the unreported count is kept apart from the tokens, not shown as 0
    assert len(doc["usage"]["by_repo"]) == 1 and len(doc["usage"]["by_day"]) == 1


def test_a_run_with_no_attempts_has_empty_usage_groups(app, home, tmp_path):
    make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    _, doc = get_json(app, "/api/runs/fix-a-aaaaa")
    assert doc["usage"] == {"by_model": {}, "by_repo": {}, "by_day": {}}


def test_the_page_renders_each_usage_group_and_the_empty_state(app):
    body = app.handle("GET", "/", {"Host": HOST}, b"").body.decode()
    for needle in ("function usageSection", "usageSection(run.usage)", '"by_model"', '"by_repo"', '"by_day"',
                   "No usage recorded yet.", "without a count"):
        assert needle in body, needle


# --- the app module exports the route surface the spec lists ---

def test_the_spec_routes_are_all_wired(app):
    assert app_module.PATH_PARTS.fullmatch("/api/runs/fix-a-aaaaa/decide")
    assert app_module.PATH_PARTS.fullmatch("/api/runs/fix-a-aaaaa/retry")
    assert app_module.TASK_LOG.fullmatch("/api/runs/fix-a-aaaaa/tasks/backend/log")
    assert app_module.DECISION.fullmatch("/runs/fix-a-aaaaa/decisions/propose.1.html")
