"""Fixtures for the dashboard tests (module 15): a home folder, a held lock, the app and a fake launcher.
Plain helpers live in helpers.py, next to this file."""

from datetime import datetime

import pytest

from factory_engine.lock import release
from factory_launcher.server.app import App
from factory_launcher.server.settings import Settings

from helpers import PORT, TOKEN, FakeLauncher


@pytest.fixture
def now():
    return datetime.now().astimezone()


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(h))
    return h


@pytest.fixture
def held():
    """Locks taken by a test to make a run `running` with a live engine. Released at the end."""
    locks = []
    yield locks
    for lock in locks:
        release(lock)


@pytest.fixture
def settings(home):
    return Settings(home=home, port=PORT)


@pytest.fixture
def launcher():
    return FakeLauncher()


@pytest.fixture
def app(settings, launcher, now):
    return App(settings, token=TOKEN, launcher=launcher, clock=lambda: now)
