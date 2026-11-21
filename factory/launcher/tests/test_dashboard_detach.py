"""`factory dashboard --detach` leaves a server running after the command returns (module 16, item 30).

The test runs the real command in a subprocess, reads the token from dashboard.json, and fetches the page. Before this
fix the server died with the command, so the fetch failed.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _fetch(url: str, token: str) -> int:
    req = urllib.request.Request(url, headers={"X-Factory-Token": token})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def test_detach_keeps_the_server_running_after_the_command_returns(home):
    port = _free_port()
    env = dict(os.environ, FACTORY_HOME=str(home))
    out = subprocess.run([sys.executable, "-m", "factory_launcher", "dashboard", "--detach", "--port", str(port)],
                         env=env, capture_output=True, text=True, timeout=30)
    info = None
    try:
        assert out.returncode == 0, out.stderr
        info = json.loads((home / "dashboard.json").read_text())
        assert info["port"] == port
        # The server is a separate process, so it outlives the command that started it.
        os.kill(info["pid"], 0)
        time.sleep(0.5)
        assert _fetch(f"http://127.0.0.1:{port}/api/state.json", info["token"]) == 200
        assert f"http://127.0.0.1:{port}/?token={info['token']}" in out.stdout
    finally:
        if info is not None:
            try:
                os.kill(info["pid"], signal.SIGTERM)
            except OSError:
                pass
