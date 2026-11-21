"""`factory watch --every` runs the same tick as the scheduler, once per interval, in the foreground (module 6, module 16).

The tick is replaced with a recorder and the sleep with a list, so no process starts and no real time passes.
"""

import json

import pytest

from factory_engine import state
from factory_engine.errors import EXIT_OK
from factory_launcher import cli, tick as tick_mod


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(h))
    return h


@pytest.fixture
def ticks(monkeypatch):
    """Records each tick call: the repos it was given. Returns a report that started nothing."""
    calls: list[list[str]] = []

    def fake_tick(cfg, *, repos, home=None, **kw):
        calls.append([str(r) for r in repos])
        return tick_mod.TickReport(started=["run-1"] if len(calls) == 2 else [])

    monkeypatch.setattr(cli.tick_mod, "tick", fake_tick)
    return calls


def _watch(argv, home, sleeps, rounds):
    args = cli._parser().parse_args(["watch", *argv])
    return cli._watch(args, home, sleep=sleeps.append, rounds=rounds)


def test_watch_ticks_once_then_waits_the_interval_between_ticks(home, ticks, capsys):
    sleeps: list[float] = []
    assert _watch(["--every", "30s", "--json"], home, sleeps, rounds=3) == EXIT_OK
    assert len(ticks) == 3
    assert sleeps == [30, 30]  # no wait after the last tick


def test_watch_prints_one_json_line_per_tick_in_the_tick_shape(home, ticks, capsys):
    _watch(["--every", "1m", "--json"], home, [], rounds=2)
    lines = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) == 2
    assert lines[1]["data"]["started"] == ["run-1"] and lines[1]["code"] == "ok"
    assert set(lines[0]["data"]) >= {"skipped_tick", "started", "resumed", "errors"}


def test_watch_passes_the_repos_it_was_given_to_each_tick(home, ticks, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _watch(["--every", "1m", "--repo", str(repo)], home, [], rounds=2)
    assert ticks == [[str(repo.resolve())], [str(repo.resolve())]]


def test_watch_rejects_an_interval_that_is_not_one(home, ticks):
    from factory_engine.errors import FactoryError
    with pytest.raises(FactoryError) as e:
        _watch(["--every", "soon"], home, [], rounds=1)
    assert e.value.code == "config.invalid" and ticks == []


def test_watch_stops_quietly_on_ctrl_c(home, monkeypatch, capsys):
    def interrupted(cfg, **kw):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli.tick_mod, "tick", interrupted)
    args = cli._parser().parse_args(["watch", "--every", "1m"])
    assert cli._watch(args, home, sleep=lambda s: None, rounds=None) == EXIT_OK


def test_watch_is_a_machine_command_so_it_never_goes_to_an_engine(monkeypatch):
    assert "watch" in cli.MACHINE and "watch" not in cli.RUN_COMMANDS
