"""Module 15 rules: the token, the Host and Origin checks, and a refused request changes nothing."""

import json
import os
import socket
import stat
import threading
import urllib.request
from pathlib import Path

import pytest

from factory_launcher.server import security
from factory_launcher.server.serve import start, write_info
from factory_launcher.server.settings import Settings

from helpers import HOST, ORIGIN, PORT, TOKEN, FakeLauncher, call, get_json, make_repo, make_run


def _snapshot(home: Path) -> dict:
    """Every file under the factory home, with its bytes. A refused request must leave this unchanged."""
    return {str(p.relative_to(home)): p.read_bytes() for p in sorted(home.rglob("*")) if p.is_file()}


# --- criterion: no token, wrong token, foreign Host or foreign Origin is refused with 403 and changes nothing ---

@pytest.fixture
def seeded(home, tmp_path):
    ref = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    return ref


def test_a_request_with_no_token_is_refused_with_403(app, seeded, home):
    before = _snapshot(home)
    resp = call(app, "GET", "/api/state.json", token=None)
    assert resp.status == 403
    assert _snapshot(home) == before


def test_a_request_with_a_wrong_token_is_refused_with_403(app, seeded, home):
    before = _snapshot(home)
    assert call(app, "GET", "/api/state.json", token="wrong").status == 403
    assert call(app, "GET", "/api/runs/fix-a-aaaaa", token="").status == 403
    assert _snapshot(home) == before


def test_a_foreign_host_is_refused_with_403(app, seeded, home):
    before = _snapshot(home)
    assert call(app, "GET", "/api/state.json", host="evil.example:8765").status == 403
    assert call(app, "GET", "/api/state.json", host="127.0.0.1:9999").status == 403
    assert call(app, "GET", "/api/state.json", host=None).status == 403
    assert _snapshot(home) == before


def test_a_foreign_origin_on_a_post_is_refused_and_no_launcher_call_is_made(app, seeded, home, launcher):
    before = _snapshot(home)
    resp = call(app, "POST", "/api/runs/fix-a-aaaaa/retry", origin="http://evil.example", body={})
    assert resp.status == 403
    assert launcher.calls == []
    assert _snapshot(home) == before


def test_a_post_with_no_origin_is_refused(app, seeded, launcher):
    assert call(app, "POST", "/api/runs/fix-a-aaaaa/retry", origin=None, body={}).status == 403
    assert launcher.calls == []


def test_a_post_from_the_dashboard_origin_reaches_the_launcher(app, seeded, launcher):
    resp = call(app, "POST", "/api/runs/fix-a-aaaaa/retry", origin=ORIGIN, body={})
    assert resp.status == 200
    assert launcher.calls == [["retry", "fix-a-aaaaa", "--json"]]


def test_the_origin_check_is_on_the_port_too(app, seeded, launcher):
    assert call(app, "POST", "/api/runs/fix-a-aaaaa/retry", origin="http://127.0.0.1:9999", body={}).status == 403


def test_no_token_wrong_token_foreign_host_or_foreign_origin_is_403_and_changes_nothing(app, seeded, home, launcher):
    """The whole criterion in one place. The token and Host refusals apply to reads and writes. The Origin refusal
    applies to POST (the spec's rule: a web page cannot send commands), and none of the refusals changes a file or
    calls the launcher."""
    before = _snapshot(home)
    for kwargs in (dict(token=None), dict(token="wrong"), dict(host="evil.example:8765")):
        assert call(app, "GET", "/api/state.json", **kwargs).status == 403, kwargs
        assert call(app, "POST", "/api/runs/fix-a-aaaaa/retry", origin=ORIGIN, body={}, **kwargs).status == 403, kwargs
    assert call(app, "POST", "/api/runs/fix-a-aaaaa/retry", origin="http://evil.example", body={}).status == 403
    assert _snapshot(home) == before
    assert launcher.calls == []


# --- the token travels in a header, and the decision page may carry it in its URL ---

def test_the_token_header_is_accepted(app, seeded):
    assert call(app, "GET", "/api/state.json").status == 200


def test_the_token_in_a_query_string_is_not_accepted_on_api_routes(app, seeded):
    resp = app.handle("GET", f"/api/state.json?token={TOKEN}", {"Host": HOST}, b"")
    assert resp.status == 403


def test_the_decision_page_route_accepts_the_token_in_the_url(app, seeded):
    resp = app.handle("GET", f"/runs/fix-a-aaaaa/decisions/propose.1.html?token={TOKEN}", {"Host": HOST}, b"")
    assert resp.status == 404  # the token passed; there is no page yet
    refused = app.handle("GET", "/runs/fix-a-aaaaa/decisions/propose.1.html?token=wrong", {"Host": HOST}, b"")
    assert refused.status == 403


def test_the_token_is_checked_before_the_route_is_chosen(app, seeded):
    """An unknown /api path with no token is refused as 403, so the surface is not revealed to a stranger."""
    assert call(app, "GET", "/api/nope", token=None).status == 403


def test_the_page_itself_needs_no_token(app):
    resp = app.handle("GET", "/", {"Host": HOST}, b"")
    assert resp.status == 200 and resp.content_type.startswith("text/html")


def test_a_refused_write_changes_nothing_on_disk(app, seeded, home):
    before = _snapshot(home)
    note = {"task": "backend", "text": "hi"}
    assert call(app, "POST", "/api/runs/fix-a-aaaaa/note", token=None, origin=ORIGIN, body=note).status == 403
    assert call(app, "POST", "/api/runs/fix-a-aaaaa/note", token="x", origin=ORIGIN, body=note).status == 403
    assert call(app, "POST", "/api/runs/fix-a-aaaaa/note", host="evil:8765", origin=ORIGIN, body=note).status == 403
    assert call(app, "POST", "/api/runs/fix-a-aaaaa/note", origin="http://evil", body=note).status == 403
    assert _snapshot(home) == before


# --- the session token: a new one at each start, stored in dashboard.json with mode 0600 ---

def test_each_start_makes_a_new_token(settings):
    a = security.new_token()
    b = security.new_token()
    assert a != b and len(a) >= 40


def test_dashboard_json_holds_pid_port_and_token_with_mode_0600(home):
    path = write_info(home, pid=4321, port=PORT, token="abc")
    assert json.loads(path.read_text()) == {"pid": 4321, "port": PORT, "token": "abc"}
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_the_server_refuses_a_second_start_on_a_taken_port(home, tmp_path):
    busy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    port = busy.getsockname()[1]
    try:
        from factory_engine.errors import FactoryError
        with pytest.raises(FactoryError) as err:
            start(Settings(home=home, port=port), launcher=FakeLauncher(), token=TOKEN)
        assert err.value.code == "dashboard.port_in_use" and err.value.exit_code == 2
    finally:
        busy.close()


def test_start_writes_dashboard_json_and_the_printed_url_carries_the_token(home):
    running = start(Settings(home=home, port=0), launcher=FakeLauncher(), token=TOKEN)
    try:
        info = json.loads((home / "dashboard.json").read_text())
        assert info["token"] == TOKEN and info["port"] == running.server.server_address[1]
        assert running.url.endswith(f"/?token={TOKEN}") and running.url.startswith("http://127.0.0.1:")
    finally:
        running.close()
    assert not (home / "dashboard.json").exists()


def test_a_real_socket_refuses_a_foreign_host_header(home, seeded):
    """Over a real socket: the Host header that the browser sends is what counts, not the address dialled."""
    running = start(Settings(home=home, port=0), launcher=FakeLauncher(), token=TOKEN)
    thread = threading.Thread(target=running.server.serve_forever, daemon=True)
    thread.start()
    try:
        port = running.server.server_address[1]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/state.json",
                                     headers={"X-Factory-Token": TOKEN, "Host": "evil.example"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        assert err.value.code == 403
    finally:
        running.server.shutdown()
        running.close()
