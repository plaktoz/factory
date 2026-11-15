"""Starts the dashboard on 127.0.0.1 (module 15): a new session token, dashboard.json (mode 0600), then the HTTP loop.

`factory dashboard` (module 16) calls start(). Run it directly for local use:
    python -m factory_launcher.server --port 8765
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from factory_engine.atomic import write_json_atomic
from factory_engine.errors import FactoryError
from factory_engine.state import factory_home

from .app import App, Response
from .launcher import Launcher, SubprocessLauncher
from .security import new_token
from .settings import DEFAULT_PORT, HOST, Settings, settings_from_home

MAX_BODY = 1_000_000  # bytes; a decision answer or a note is far smaller


@dataclass
class Running:
    server: ThreadingHTTPServer
    url: str
    token: str
    info_path: Path

    def close(self) -> None:
        self.server.server_close()
        try:
            self.info_path.unlink()
        except OSError:
            pass


def _handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "factory-dashboard"

        def _run(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._send(Response(413, b'{"ok": false, "code": "dashboard.bad_request", '
                                         b'"message": "body too large", "hint": "", "data": {}}',
                                    "application/json; charset=utf-8"))
                return
            body = self.rfile.read(length) if length else b""
            resp = app.handle(method, self.path, dict(self.headers.items()), body)
            self._send(resp)

        def _send(self, resp: Response) -> None:
            self.send_response(resp.status)
            self.send_header("Content-Type", resp.content_type)
            self.send_header("Content-Length", str(len(resp.body)))
            for k, v in resp.headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(resp.body)

        def do_GET(self) -> None:  # noqa: N802 - the http.server name
            self._run("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._run("POST")

        def log_message(self, format: str, *args) -> None:  # quiet: the page polls every 5 s
            return None

    return Handler


def write_info(home: Path, *, pid: int, port: int, token: str) -> Path:
    """dashboard.json: the pid, the port and the token, readable by this user only (module 15)."""
    path = home / "dashboard.json"
    write_json_atomic(path, {"pid": pid, "port": port, "token": token})
    os.chmod(path, 0o600)
    return path


def start(settings: Settings, *, launcher: Launcher | None = None, token: str | None = None) -> Running:
    """Bind the port (fails fast when it is taken), write dashboard.json, and return the running server. The caller
    runs serve_forever(). Port 0 asks the OS for a free port; the app then checks Host and Origin against that port."""
    token = token or new_token()
    app = App(settings, token=token, launcher=launcher or SubprocessLauncher(home=settings.home))
    try:
        server = ThreadingHTTPServer((HOST, settings.port), _handler(app))
    except OSError as e:
        raise FactoryError("dashboard.port_in_use", f"port {settings.port} on {HOST} is not free: {e}",
                           hint=f"stop the process using port {settings.port}, or pass another --port") from e
    port = server.server_address[1]
    app.settings = replace(settings, port=port)
    info = write_info(settings.home, pid=os.getpid(), port=port, token=token)
    url = f"http://{HOST}:{port}/?token={token}"
    return Running(server, url, token, info)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="factory_launcher.server", description="Run the factory dashboard.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    home = factory_home()
    settings = settings_from_home(home, port=args.port)
    try:
        running = start(settings)
    except FactoryError as e:
        print(f"{e.code}: {e.message}\nhint: {e.hint}", file=sys.stderr)
        return 1
    print(running.url, flush=True)
    try:
        running.server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        running.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
