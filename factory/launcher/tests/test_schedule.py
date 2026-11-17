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
