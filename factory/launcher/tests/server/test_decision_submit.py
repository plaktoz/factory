"""Module 15, L100 (1b): Submit on a decision page records the answer through the launcher, and the run is started again.

The decision page is the engine's file (module 11, render_page). The engine writes it with no submit URL, so its Submit
button is hidden on disk, and opened from disk the page still shows only the command. The dashboard turns the Submit on
when it serves the page (views.submit_wired), and the token is injected at serve time as before.

The browser tests load the served page in headless Chrome (page_harness.run_page) and click the page's own Submit button.
They skip when Chrome is absent. The launcher test runs the engine's own CLI in this process with the engine start
replaced by a recorder, so the decision file really is answered and no engine process starts.
"""

import json
import re
from contextlib import redirect_stdout
from io import StringIO

import pytest

from factory_engine import api, cli, decisions
from factory_launcher.server.launcher import LauncherResult
from page_harness import CHROME, click, fail, run_page, snap

from helpers import HOST, ORIGIN, TOKEN, approval_page, attention_for, call, make_repo, make_run, set_run

RUN = "fix-a-aaaaa"
SUBMIT = f"/api/runs/{RUN}/decide"
PAGE = f"/runs/{RUN}/decisions/propose.1.html"
TOKEN_SCRIPT = f"<script>window.FACTORY_TOKEN={json.dumps(TOKEN)};</script>"
needs_chrome = pytest.mark.skipif(not CHROME.exists(), reason="Google Chrome is not installed")


def _ready(home, tmp_path, held):
    ref = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id=RUN)
    page = approval_page(ref)
    set_run(ref, held, status="awaiting_approval", stage="propose", attention=attention_for(ref, page=page))
    return ref, page


def _served(app) -> str:
    resp = app.handle("GET", f"{PAGE}?token={TOKEN}", {"Host": HOST}, b"")
    assert resp.status == 200
    return resp.body.decode()


def _sha(ref) -> str:
    return decisions.read_decision(ref.run_dir, "propose", 1)["packet"]["sha"]


def _snapshot(home) -> dict:
    return {str(p.relative_to(home)): p.read_bytes() for p in sorted(home.rglob("*")) if p.is_file()}


def _page_body(ref, choices=None, notes="") -> dict:
    """The request shape the decision page's own script sends (module 11)."""
    return {"run": RUN, "packet": _sha(ref), "choices": choices or {"D1": "approve"}, "questions": {},
            "notes": notes, "channel": "dashboard"}


class EngineCli:
    """Stands in for `factory <args> --json`: runs the engine's own CLI in this process and returns its JSON document."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(list(args))
        out = StringIO()
        with redirect_stdout(out):
            code = cli.main(list(args))
        doc = json.loads(out.getvalue().strip().splitlines()[-1])
        return LauncherResult(doc, code, "")


# --- the served page carries the Submit wiring -------------------------------------------------------------------

def test_the_served_decision_page_has_a_submit_button_that_targets_the_decide_route(app, home, tmp_path, held):
    _ready(home, tmp_path, held)
    text = _served(app)
    assert 'id="submit"' in text
    assert f'data-submit-url="{SUBMIT}"' in text


def test_the_served_page_may_connect_to_its_own_origin_and_nothing_else(app, home, tmp_path, held):
    _ready(home, tmp_path, held)
    text = _served(app)
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]*)"', text).group(1)
    assert "connect-src &#x27;self&#x27;" in policy and "default-src &#x27;none&#x27;" in policy
    assert "form-action &#x27;none&#x27;" in policy and "unsafe-eval" not in policy
    header = app.handle("GET", f"{PAGE}?token={TOKEN}", {"Host": HOST}, b"").headers["Content-Security-Policy"]
    assert "connect-src 'self'" in header and "form-action 'none'" in header


def test_serving_the_page_changes_only_the_submit_wiring_and_the_token(app, home, tmp_path, held):
    """The served page is the file on disk plus the token script, the submit URL and the connect rule. Nothing else."""
    ref, page = _ready(home, tmp_path, held)
    on_disk = page.read_text()
    before = page.read_bytes()
    served = _served(app).replace(TOKEN_SCRIPT, "", 1)

    def normalize(text: str) -> str:
        text = re.sub(r'data-submit-url="[^"]*"', 'data-submit-url=""', text, count=1)
        return re.sub(r'<meta http-equiv="Content-Security-Policy" content="[^"]*">', "<meta csp>", text, count=1)

    assert normalize(served) == normalize(on_disk)
    assert page.read_bytes() == before  # the file on disk is not rewritten
    assert TOKEN not in on_disk


def test_a_page_the_engine_wrote_without_a_submit_url_is_served_with_the_submit_url(app, home, tmp_path, held):
    ref, page = _ready(home, tmp_path, held)
    assert 'data-submit-url=""' in page.read_text()  # what the engine writes
    assert f'data-submit-url="{SUBMIT}"' in _served(app)


# --- the launcher records the answer and starts the engine ---------------------------------------------------------

def test_submit_records_the_answer_through_the_cli_and_requests_an_engine_start(app, home, tmp_path, held,
                                                                              monkeypatch):
    ref, _ = _ready(home, tmp_path, held)
    spawned: list[str] = []
    monkeypatch.setattr(api, "spawn_engine", lambda repo, run_id: spawned.append(run_id) or 4242)
    engine = EngineCli()
    app.launcher = engine

    resp = call(app, "POST", SUBMIT, origin=ORIGIN, body=_page_body(ref))

    assert resp.status == 200, resp.body
    doc = json.loads(resp.body)
    assert doc["ok"] is True and doc["data"]["status"] == "approved" and doc["data"]["started_pid"] == 4242
    answered = decisions.read_decision(ref.run_dir, "propose", 1)["decision"]
    assert answered["status"] == "approved" and answered["choices"] == {"D1": "approve"}
    assert spawned == [RUN]  # the engine start is requested, as the decide route does for an approval


def test_the_page_request_shape_reaches_the_launcher_as_a_decide_command(app, home, tmp_path, held, launcher):
    ref, _ = _ready(home, tmp_path, held)
    resp = call(app, "POST", SUBMIT, origin=ORIGIN, body=_page_body(ref, notes="Keep it simple"))
    assert resp.status == 200
    assert launcher.calls == [["decide", RUN, "--packet", _sha(ref), "D1=approve", "--notes", "Keep it simple",
                               "--json"]]


# --- a refused submit changes nothing ------------------------------------------------------------------------------

def test_a_submit_with_a_wrong_token_no_token_or_a_foreign_origin_is_403_and_changes_nothing(app, home, tmp_path,
                                                                                            held, launcher):
    ref, _ = _ready(home, tmp_path, held)
    body = _page_body(ref)
    before = _snapshot(home)
    assert call(app, "POST", SUBMIT, token="wrong", origin=ORIGIN, body=body).status == 403
    assert call(app, "POST", SUBMIT, token=None, origin=ORIGIN, body=body).status == 403
    assert call(app, "POST", SUBMIT, origin=None, body=body).status == 403
    assert call(app, "POST", SUBMIT, origin="http://evil.example", body=body).status == 403
    assert launcher.calls == []
    assert _snapshot(home) == before


# --- the browser: the served page's own Submit button -------------------------------------------------------------

SUBMITTED = "function(){return document.getElementById('submitted').textContent;}"
SUBMIT_SHOWN = "function(){return !document.getElementById('submit').hidden;}"
OK_BODY = json.dumps({"ok": True, "code": "ok", "message": f"{RUN} propose: approved", "hint": "",
                      "data": {"status": "approved"}})
ERROR_BODY = json.dumps({"ok": False, "code": "decision.stale_packet", "message": "packet changed", "hint": "",
                         "data": {}})


@needs_chrome
def test_submit_posts_the_picks_to_the_decide_route_with_the_session_token(app, home, tmp_path, held):
    ref, _ = _ready(home, tmp_path, held)
    out = run_page(tmp_path, {SUBMIT: OK_BODY}, [
        (1000, click("#submit")),
        (1500, snap("shown", SUBMIT_SHOWN)),
        (1600, snap("result", SUBMITTED)),
    ], token=TOKEN, page_text=_served(app))
    posts = [f for f in out["fetches"] if f["path"] == SUBMIT]
    assert len(posts) == 1, out
    assert posts[0]["method"] == "POST" and posts[0]["token"] == TOKEN
    sent = json.loads(posts[0]["body"])
    assert sent["packet"] == _sha(ref) and sent["choices"] == {"D1": "approve"}
    assert out["snaps"]["shown"] is True
    assert out["snaps"]["result"] == "Sent"
    assert out["errors"] == []


@needs_chrome
def test_submit_shows_the_launcher_error_code_inline(app, home, tmp_path, held):
    _ready(home, tmp_path, held)
    out = run_page(tmp_path, {}, [
        (800, fail(SUBMIT, ERROR_BODY)),
        (1000, click("#submit")),
        (1600, snap("result", SUBMITTED)),
    ], token=TOKEN, page_text=_served(app))
    assert "decision.stale_packet" in out["snaps"]["result"], out
