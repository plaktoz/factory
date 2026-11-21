"""`factory inbox` and `factory dashboard` (module 16): both exist, take `--json` and answer in the shared shape.

The dashboard server start is replaced with a recorder, so no socket opens.
"""

import json
from types import SimpleNamespace

import pytest

from factory_engine import state
from factory_engine.lock import acquire_lock, release
from factory_engine.types import AttentionItem, Request, Source
from factory_launcher import cli


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(h))
    return h


def _run(home, run_id, repo, attention):
    """A run the engine itself writes, so run.json passes the run schema. `attention` is its attention item, or None."""
    request = Request(request_id=run_id, source=Source("cli", run_id, "t", "", [], None, []), body_sha="", repo=repo.name,
                      title="t", type=None, type_source=None, priority=None, acceptance=[])
    ref = state.init_run(home, repo, "local/repo", run_id, request, branch=None, worktree=repo, kit_hash="aaaa")
    run = state.read_run(ref.run_dir)
    run.attention = attention
    lock = acquire_lock(ref.run_dir, "engine")
    try:
        state.write_run(ref.run_dir, run, lock=lock)
    finally:
        release(lock)


def _item(run_id):
    return AttentionItem(kind="decision", run_id=run_id, stage="propose", since="2026-11-21T00:00:00+00:00",
                         summary="choose a fix", page=None, command="factory decide " + run_id)


def _inbox(argv, home):
    return cli._inbox(cli._parser().parse_args(["inbox", *argv]), home)


def test_inbox_says_nothing_needs_you_when_no_run_has_an_attention_item(home, tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(home, "run-quiet", repo, None)

    assert _inbox([], home) == 0
    assert "nothing needs you" in capsys.readouterr().out


def test_inbox_json_lists_only_the_runs_that_need_attention(home, tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(home, "run-quiet", repo, None)
    _run(home, "run-waiting", repo, _item("run-waiting"))

    assert _inbox(["--json"], home) == 0
    out = json.loads(capsys.readouterr().out)

    assert out["ok"] is True and out["code"] == "ok"
    assert [i["run_id"] for i in out["data"]["items"]] == ["run-waiting"]
    assert out["data"]["items"][0]["kind"] == "decision"
    assert out["data"]["items"][0]["command"] == "factory decide run-waiting"


def test_inbox_text_names_the_run_and_its_kind(home, tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(home, "run-waiting", repo, _item("run-waiting"))

    _inbox([], home)

    assert "run-waiting [decision] choose a fix" in capsys.readouterr().out


@pytest.fixture
def server(monkeypatch):
    """Replaces the dashboard server start. Records the port it was asked for and returns a fake running server."""
    calls = []

    def fake_start(settings):
        calls.append(settings)
        return SimpleNamespace(url="http://127.0.0.1:%d/" % settings.port, server=SimpleNamespace(serve_forever=lambda: None))

    monkeypatch.setattr("factory_launcher.server.serve.start", fake_start)
    return calls


def _dashboard(argv, home):
    return cli._dashboard(cli._parser().parse_args(["dashboard", *argv]), home)


def test_dashboard_detach_json_reports_the_url_and_port_and_returns_at_once(home, server, capsys):
    assert _dashboard(["--port", "8799", "--detach", "--json"], home) == 0
    out = json.loads(capsys.readouterr().out)

    assert out["ok"] is True
    assert out["data"] == {"url": "http://127.0.0.1:8799/", "port": 8799}
    assert [s.port for s in server] == [8799]


def test_dashboard_default_port_is_8765(home, server):
    _dashboard(["--detach"], home)

    assert [s.port for s in server] == [8765]
