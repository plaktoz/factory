"""Module 16 acceptance for the machine rows: every machine command of the table exists, prints the shared `--json` shape,
and exits with a shared code. The engine's rows are in factory/engine/tests/drivers/test_command_table.py.

The machine rows are `tick`, `watch`, `schedule` (install, remove, at), `dashboard`, `inbox`, `doctor` and `config init`.
Most have a success case and an error case. `inbox` has only its success case, and `tick` has a success case and a
lock-held case.
Every OS and network effect is replaced: the scheduler writes into a temporary folder, the dashboard server and its
detached child are recorders, and the tick is a recorder, so no process starts and nothing is loaded.
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from factory_engine.errors import EXIT_INVALID, EXIT_OK
from factory_launcher import cli, schedule, tick as tick_mod

SHARED_CODES = {0, 1, 2, 3, 4, 5}
SHAPE = {"ok", "code", "message", "hint", "data"}
MACHINE_ROWS = ["tick", "watch", "schedule", "dashboard", "inbox", "doctor", "config"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(h))
    monkeypatch.chdir(tmp_path)  # not inside a git repo, so no repo is found by accident
    return h


def _doc(capsys):
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    return json.loads(lines[-1])


def _assert_shape(doc, code, *, ok):
    assert set(doc) == SHAPE, doc
    assert doc["ok"] is ok and code in SHARED_CODES


# ---- every machine row answers a bad flag with the shared shape and exit 2 -------------------------------------------

@pytest.mark.parametrize("command", MACHINE_ROWS)
def test_every_machine_row_answers_a_bad_flag_with_the_shared_shape_and_exit_2(command, home, capsys):
    """argparse exits 2 on a bad flag. With --json that is the shared shape on stdout, not argparse text."""
    with pytest.raises(SystemExit) as e:
        cli.main([command, "--bogus-flag", "--json"])
    assert e.value.code == EXIT_INVALID
    doc = json.loads(capsys.readouterr().out)
    _assert_shape(doc, e.value.code, ok=False)
    assert doc["code"] == "cli.usage"


def test_every_machine_row_exists_as_a_subcommand():
    names = set(cli._parser()._subparsers._group_actions[0].choices)
    assert set(MACHINE_ROWS) <= names, sorted(set(MACHINE_ROWS) - names)


# ---- one success and one error case for the rows the engine table does not cover -------------------------------------

@pytest.fixture
def ticks(monkeypatch):
    monkeypatch.setattr(cli.tick_mod, "tick",
                        lambda cfg, *, repos, home=None, **kw: tick_mod.TickReport(started=[], skipped_tick=False))


def test_tick_prints_the_shared_shape_and_exits_0(home, ticks, capsys):
    code = cli.main(["tick", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["code"] == "ok"


def test_tick_with_another_tick_holding_the_lock_still_exits_0_and_says_so(home, monkeypatch, capsys):
    monkeypatch.setattr(cli.tick_mod, "tick",
                        lambda cfg, *, repos, home=None, **kw: tick_mod.TickReport(skipped_tick=True))
    code = cli.main(["tick", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["code"] == "tick_skipped"


def test_watch_prints_the_shared_shape_per_tick(home, ticks, monkeypatch, capsys):
    real_watch = cli._watch
    monkeypatch.setattr(cli, "_watch", lambda args, home: real_watch(args, home, sleep=lambda s: None, rounds=1))
    code = cli.main(["watch", "--every", "1m", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=True)
    assert code == EXIT_OK


def test_watch_with_a_bad_interval_is_a_config_error_in_the_shared_shape(home, ticks, capsys):
    code = cli.main(["watch", "--every", "soon", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=False)
    assert code == EXIT_INVALID and doc["code"] == "config.invalid"


@pytest.fixture
def scheduler(home, tmp_path, monkeypatch):
    """Writes the scheduler entry into a temporary folder and loads nothing."""
    target = tmp_path / "agents"
    monkeypatch.setattr(schedule, "_system", lambda: "Darwin")
    monkeypatch.setattr(schedule.Path, "home", classmethod(lambda cls: tmp_path))
    return target


def test_schedule_install_prints_the_shared_shape_and_writes_the_entry(home, scheduler, tmp_path, capsys):
    code = cli.main(["schedule", "install", "--every", "10m", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=True)
    assert code == EXIT_OK and (tmp_path / "Library" / "LaunchAgents" / f"{schedule.LABEL}.plist").is_file()


def test_schedule_install_with_a_bad_interval_is_a_config_error(home, scheduler, capsys):
    code = cli.main(["schedule", "install", "--every", "ten", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=False)
    assert code == EXIT_INVALID and doc["code"] == "config.invalid"


def test_schedule_remove_prints_the_shared_shape_and_says_what_it_removed(home, scheduler, capsys):
    code = cli.main(["schedule", "remove", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"] == {"removed": False}


def test_schedule_at_with_a_past_time_is_a_config_error(home, scheduler, capsys):
    code = cli.main(["schedule", "at", "--at", "2001-01-01T09:00", "--name", "old-job", "--json", "--", "true"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=False)
    assert code == EXIT_INVALID


def test_schedule_remove_once_with_no_such_job_says_nothing_to_remove(home, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(schedule.Path, "home", classmethod(lambda cls: tmp_path))
    code = cli.main(["schedule", "remove", "--name", "no-such-job", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"] == {"removed": False}


def test_dashboard_prints_the_shared_shape_with_its_url(home, monkeypatch, capsys):
    calls: list = []
    monkeypatch.setattr("factory_launcher.server.serve.start", lambda settings: (calls.append(settings) or SimpleNamespace(
        url="http://127.0.0.1:%d/" % settings.port, server=SimpleNamespace(serve_forever=lambda: (_ for _ in ()).throw(
            KeyboardInterrupt)))))
    code = cli.main(["dashboard", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"]["port"] == 8765


def test_dashboard_detach_with_the_port_taken_is_a_config_error_in_the_shared_shape(home, monkeypatch, capsys):
    """The detached child exits at once because the port is taken; the command reports dashboard.port_in_use, exit 2."""
    log = home / "dashboard-start.log"
    log.write_text("dashboard.port_in_use: port 8765 is in use\nhint: pass --port\n")
    child = SimpleNamespace(pid=1, poll=lambda: 1, returncode=1, kill=lambda: None)
    monkeypatch.setattr(cli, "_spawn_dashboard_child", lambda argv, home: child)
    code = cli.main(["dashboard", "--detach", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=False)
    assert code == EXIT_INVALID and doc["code"] == "dashboard.port_in_use"


def test_inbox_prints_the_shared_shape_and_its_items(home, capsys):
    code = cli.main(["inbox", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"] == {"items": []}


def test_doctor_no_repo_prints_the_shared_shape_per_check(home, capsys):
    code = cli.main(["doctor", "--no-repo", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=doc["ok"])
    assert code in (EXIT_OK, 1) and "checks" in doc["data"]


def test_doctor_with_a_failed_check_exits_1_in_the_shared_shape(home, monkeypatch, capsys):
    from factory_engine.types import CheckResult
    monkeypatch.setattr(cli.api, "doctor", lambda repo, as_scheduler=False: [CheckResult("gh", False, "", "log in")])
    code = cli.main(["doctor", "--no-repo", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=False)
    assert code == 1 and doc["code"] == "failed"


def test_config_init_writes_the_machine_file_and_prints_the_shared_shape(home, capsys):
    code = cli.main(["config", "init", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"]["created"] is True and (home / "config.yaml").is_file()


def test_config_init_twice_says_the_file_already_exists(home, capsys):
    cli.main(["config", "init", "--json"])
    capsys.readouterr()
    code = cli.main(["config", "init", "--json"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"]["created"] is False


def test_schedule_at_writes_the_one_shot_entry_and_prints_the_shared_shape(home, tmp_path, monkeypatch, capsys):
    """`schedule at` takes its command after `--`; the entry goes to a temporary folder and nothing is loaded."""
    seen = {}
    # `cli.main` reads the real clock, so the time is built from it: a day ahead, to the minute, in the future on any run.
    at = (datetime.now() + timedelta(days=1)).replace(second=0, microsecond=0)

    def fake_install_once(name, when, command, home, cwd):
        seen.update(name=name, when=when, command=command)
        return tmp_path / "job.plist"

    monkeypatch.setattr(cli.schedule_mod, "install_once", fake_install_once)
    code = cli.main(["schedule", "at", "--at", at.strftime("%Y-%m-%dT%H:%M"), "--name", "pilot", "--json", "--", "python3", "-c", "1"])
    doc = _doc(capsys)
    _assert_shape(doc, code, ok=True)
    assert code == EXIT_OK and seen == {"name": "pilot", "when": at, "command": ["python3", "-c", "1"]}


ENGINE_ROWS = ["init", "upgrade", "add", "sync", "run", "decide", "check", "reopen", "open", "note", "retry", "goto",
               "skip", "abort", "resume", "recover", "status", "where", "events", "usage", "gc"]


@pytest.mark.parametrize("command", ENGINE_ROWS)
def test_every_engine_row_is_handed_to_the_engine_with_its_json_flag_and_exit_code(command, home, tmp_path, monkeypatch):
    """The launcher does not parse a run command: it passes argv, `--json` included, and the engine's exit code through."""
    repo = tmp_path / "repo"
    repo.mkdir()
    seen = {}

    def fake_dispatch(argv, repo, home, **kw):
        seen["argv"] = argv
        return 5

    monkeypatch.setattr(cli, "_dispatch", fake_dispatch)
    assert cli.main([command, "--repo", str(repo), "--json"]) == 5
    assert seen["argv"] == [command, "--json"]


def test_a_usage_error_without_json_keeps_argparse_text_on_stderr(home, capsys):
    """Only --json changes the output; without it the usage error is argparse's own text on stderr."""
    with pytest.raises(SystemExit) as e:
        cli.main(["tick", "--bogus-flag"])
    assert e.value.code == EXIT_INVALID
    assert "unrecognized arguments" in capsys.readouterr().err
