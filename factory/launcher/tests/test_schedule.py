"""`factory schedule install --every` writes a working scheduler entry, and `remove` deletes it.

Each test points the entry at a temporary folder and checks the file's content. Nothing is loaded into launchd or
systemd, and no crontab is touched. `plutil -lint` checks the launchd plist on macOS.
"""

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from factory_engine.errors import FactoryError
from factory_launcher import schedule


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def test_an_interval_is_seconds_and_a_bare_number_is_minutes():
    assert schedule.interval_seconds("10m") == 600
    assert schedule.interval_seconds("30s") == 30
    assert schedule.interval_seconds("2h") == 7200
    assert schedule.interval_seconds("5") == 300


@pytest.mark.parametrize("bad", ["", "ten", "0m", "-5m", "10x"])
def test_a_bad_interval_is_a_config_error(bad):
    with pytest.raises(FactoryError) as e:
        schedule.interval_seconds(bad)
    assert e.value.code == "config.invalid"


def test_install_on_macos_writes_a_launchd_plist_with_the_interval(home, tmp_path):
    folder = tmp_path / "LaunchAgents"
    path = schedule.install("10m", home=home, target_dir=folder, system="Darwin")
    assert path == folder / f"{schedule.LABEL}.plist"
    doc = plistlib.loads(path.read_bytes())
    assert doc["Label"] == schedule.LABEL
    assert doc["StartInterval"] == 600
    assert doc["ProgramArguments"][-2:] == ["tick", "--all-repos"]
    assert doc["EnvironmentVariables"]["FACTORY_HOME"] == str(home)


def test_the_macos_plist_passes_plutil_lint(home, tmp_path):
    if shutil.which("plutil") is None:
        pytest.skip("plutil is macOS only")
    path = schedule.install("10m", home=home, target_dir=tmp_path / "LaunchAgents", system="Darwin")
    out = subprocess.run(["plutil", "-lint", str(path)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_install_on_linux_writes_a_systemd_timer_and_its_service(home, tmp_path):
    folder = tmp_path / "systemd"
    path = schedule.install("10m", home=home, target_dir=folder, system="Linux")
    assert path == folder / f"{schedule.UNIT}.timer"
    timer = path.read_text()
    service = (folder / f"{schedule.UNIT}.service").read_text()
    assert "OnUnitActiveSec=600s" in timer and "WantedBy=timers.target" in timer
    assert "Type=oneshot" in service and "tick --all-repos" in service
    assert f"Environment=FACTORY_HOME={home}" in service


def test_remove_deletes_the_macos_entry_and_reports_it(home, tmp_path):
    folder = tmp_path / "LaunchAgents"
    schedule.install("10m", home=home, target_dir=folder, system="Darwin")
    assert schedule.remove(home=home, target_dir=folder, system="Darwin") is True
    assert not (folder / f"{schedule.LABEL}.plist").exists()
    assert schedule.remove(home=home, target_dir=folder, system="Darwin") is False


def test_remove_deletes_both_linux_units(home, tmp_path):
    folder = tmp_path / "systemd"
    schedule.install("10m", home=home, target_dir=folder, system="Linux")
    assert schedule.remove(home=home, target_dir=folder, system="Linux") is True
    assert not (folder / f"{schedule.UNIT}.timer").exists()
    assert not (folder / f"{schedule.UNIT}.service").exists()


def test_windows_is_phase_2_and_refused(home, tmp_path):
    with pytest.raises(FactoryError) as e:
        schedule.install("10m", home=home, target_dir=tmp_path, system="Windows")
    assert e.value.code == "config.invalid" and "phase 2" in e.value.hint


def test_the_entry_starts_the_launcher_by_absolute_path(home, tmp_path):
    """A scheduler starts with almost no PATH, so the entry names the executable, not a bare `factory`."""
    folder = tmp_path / "LaunchAgents"
    path = schedule.install("10m", home=home, target_dir=folder, system="Darwin")
    program = plistlib.loads(path.read_bytes())["ProgramArguments"][0]
    assert Path(program).is_absolute() or program == sys.executable


# One-off jobs: `factory schedule at` (module 16).

from datetime import datetime, timedelta  # noqa: E402

AT = datetime(2026, 11, 25, 19, 43)


def test_an_at_time_is_local_and_must_be_in_the_future():
    now = datetime(2026, 11, 22, 12, 0)
    assert schedule.parse_at("2026-11-25T19:43", now=now) == AT
    for bad in ("tomorrow", "2026-11-21T19:43"):
        with pytest.raises(FactoryError) as e:
            schedule.parse_at(bad, now=now)
        assert e.value.code == "config.invalid"


def test_a_once_job_on_macos_fires_at_the_time_and_then_removes_itself(home, tmp_path):
    folder = tmp_path / "LaunchAgents"
    path = schedule.install_once("pilot", AT, ["python3", "-c", "pass", "a && b"], home=home, cwd=tmp_path,
                                 target_dir=folder, system="Darwin")
    doc = plistlib.loads(path.read_bytes())
    assert path == folder / "com.factory.once.pilot.plist" and doc["Label"] == "com.factory.once.pilot"
    assert doc["StartCalendarInterval"] == {"Month": 11, "Day": 25, "Hour": 19, "Minute": 43}
    assert doc["WorkingDirectory"] == str(tmp_path) and doc["EnvironmentVariables"]["FACTORY_HOME"] == str(home)
    argv = doc["ProgramArguments"]
    assert Path(argv[-4]).is_absolute() and argv[-3:] == ["-c", "pass", "a && b"]  # the argument arrives whole
    assert str(path) in argv[2] and "bootout" in argv[2]  # a calendar entry has no year, so the job unloads itself


def test_a_once_job_on_macos_passes_plutil_lint(home, tmp_path):
    if shutil.which("plutil") is None:
        pytest.skip("plutil is macOS only")
    path = schedule.install_once("pilot", AT, ["python3", "-c", "pass"], home=home, cwd=tmp_path,
                                 target_dir=tmp_path / "LaunchAgents", system="Darwin")
    assert subprocess.run(["plutil", "-lint", str(path)], capture_output=True).returncode == 0


def test_the_wrapper_runs_the_command_with_its_arguments_and_deletes_the_entry(home, tmp_path):
    """The shell text itself, run for real with launchctl's bootout absent from the picture (it only logs to /dev/null)."""
    path = schedule.install_once("pilot", AT, [sys.executable, "-c", "import sys; open(sys.argv[1], 'w').write(sys.argv[2])",
                                              str(tmp_path / "out"), "a && b"],
                                 home=home, cwd=tmp_path, target_dir=tmp_path / "LaunchAgents", system="Darwin")
    argv = plistlib.loads(path.read_bytes())["ProgramArguments"]
    assert subprocess.run(argv, capture_output=True).returncode == 0
    assert (tmp_path / "out").read_text() == "a && b"
    assert not path.exists()


def test_the_wrapper_keeps_the_commands_exit_code(home, tmp_path):
    path = schedule.install_once("pilot", AT, [sys.executable, "-c", "raise SystemExit(7)"], home=home, cwd=tmp_path,
                                 target_dir=tmp_path / "LaunchAgents", system="Darwin")
    assert subprocess.run(plistlib.loads(path.read_bytes())["ProgramArguments"]).returncode == 7
    assert not path.exists()  # a failed command still removes its entry


def test_a_once_job_on_linux_writes_a_timer_for_that_date_and_its_service(home, tmp_path):
    folder = tmp_path / "systemd"
    path = schedule.install_once("pilot", AT, [sys.executable, "-c", "pass"], home=home, cwd=tmp_path,
                                 target_dir=folder, system="Linux")
    assert path == folder / "factory-tick-once-pilot.timer"
    assert "OnCalendar=2026-11-25 19:43:00" in path.read_text()
    service = (folder / "factory-tick-once-pilot.service").read_text()
    assert "Type=oneshot" in service and f"WorkingDirectory={tmp_path}" in service


def test_a_once_job_needs_a_clean_name_a_command_that_exists_and_a_supported_system(home, tmp_path):
    kw = dict(home=home, cwd=tmp_path, target_dir=tmp_path / "t")
    for name, command, system in (("Bad Name", ["python3"], "Darwin"), ("../x", ["python3"], "Darwin"),
                                  ("ok", [], "Darwin"), ("ok", ["no-such-program-xyz"], "Darwin"),
                                  ("ok", ["python3"], "Windows")):
        with pytest.raises(FactoryError) as e:
            schedule.install_once(name, AT, command, system=system, **kw)
        assert e.value.code == "config.invalid"
    assert not (tmp_path / "t").exists()


def test_remove_once_deletes_only_that_job(home, tmp_path):
    folder = tmp_path / "LaunchAgents"
    for name in ("one", "two"):
        schedule.install_once(name, AT + timedelta(days=1), ["python3", "-c", "pass"], home=home, cwd=tmp_path,
                              target_dir=folder, system="Darwin")
    assert schedule.remove_once("one", target_dir=folder, system="Darwin") is True
    assert schedule.remove_once("one", target_dir=folder, system="Darwin") is False
    assert (folder / "com.factory.once.two.plist").exists()
