"""The dashboard's HTTP app (module 15): checks, routes and the response shape. No sockets here, so tests call handle().

Order of checks on every request: Host, then Origin on POST, then the session token on /api and decision-page paths.
A refused request gets 403 and changes nothing. Writes are sent to the launcher as a separate process.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable
from urllib.parse import parse_qs, unquote, urlsplit

from factory_engine.clock import SystemClock

from . import security, views
from .launcher import Launcher, LauncherResult
from .runs import RunIndex
from .settings import Settings

STATIC_INDEX = "index.html"
DECISION_CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'none'; "
                "form-action 'none'; connect-src 'self'")
KEY =re.compile(r"[A-Za-z0-9_-]+")
VALUE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.@-]*")  # never starts with a dash
PATH_PARTS = re.compile(r"/api/runs/([^/]+)(?:/(decide|note|retry|goto|skip|abort))?")
TASK_LOG = re.compile(r"/api/runs/([^/]+)/tasks/([^/]+)/log")
DECISION = re.compile(r"/runs/([^/]+)/decisions/([^/]+)")


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "application/json; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)


def _json(status: int, doc: dict) -> Response:
    return Response(status, (json.dumps(doc, indent=2) + "\n").encode())


def _error(status: int, code: str, message: str) -> Response:
    return _json(status, {"ok": False, "code": code, "message": message, "hint": "", "data": {}})


def _refused(reason: str) -> Response:
    return _error(403, "dashboard.refused", reason)


def _bad(message: str) -> Response:
    return _error(400, "dashboard.bad_request", message)


class App:
    def __init__(self, settings: Settings, *, token: str, launcher: Launcher,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.settings = settings
        self.token = token
        self.launcher = launcher
        self.index = RunIndex(settings.home)
        self._now = clock or SystemClock().now

    def handle(self, method: str, target: str, headers: dict[str, str], body: bytes = b"") -> Response:
        headers = {k.lower(): v for k, v in headers.items()}
        if not security.host_ok(headers.get("host"), self.settings.port):
            return _refused("Host is not the dashboard address")
        parts = urlsplit(target)
        path = unquote(parts.path)
        query = parse_qs(parts.query)
        if method == "POST" and not security.origin_ok(headers.get("origin"), self.settings.port):
            return _refused("POST must come from the dashboard origin")
        if method not in ("GET", "POST"):
            return _error(405, "dashboard.method", f"{method} is not allowed")

        if path == "/" or path == f"/{STATIC_INDEX}":
            return self._static_index(method)
        is_page = DECISION.fullmatch(path) is not None
        if path.startswith("/api/") or is_page:
            presented = headers.get(security.TOKEN_HEADER.lower())
            if presented is None and is_page:  # Open page is a plain link, so a page may carry the token in its URL
                presented = (query.get("token") or [None])[0]
            if not security.token_ok(presented, self.token):
                return _refused("missing or wrong session token")
            return self._api(method, path, body)
        return _error(404, "dashboard.not_found", f"no route for {path}")

    # --- pages -----------------------------------------------------------------------------------

    def _static_index(self, method: str) -> Response:
        if method != "GET":
            return _error(405, "dashboard.method", "GET only")
        page = self.settings.static_dir / STATIC_INDEX
        if not page.is_file():
            return _error(404, "dashboard.no_page", f"{page} is missing")
        return Response(200, page.read_bytes(), "text/html; charset=utf-8", _security_headers())

    def _decision(self, run_id: str, name: str) -> Response:
        path = views.decision_page(self.index, run_id, name)
        if path is None:
            return _error(404, "dashboard.not_found", f"no decision page {name} for run {run_id}")
        text = views.submit_wired(path.read_bytes().decode("utf-8", errors="replace"), run_id)
        # The token is injected when the page is served, never written to the file on disk.
        script = f"<script>window.FACTORY_TOKEN={json.dumps(self.token)};</script>"
        text = text.replace("</head>", script + "</head>", 1) if "</head>" in text else script + text
        headers = {**_security_headers(), "Content-Security-Policy": DECISION_CSP}
        return Response(200, text.encode(), "text/html; charset=utf-8", headers)

    # --- api -------------------------------------------------------------------------------------

    def _api(self, method: str, path: str, body: bytes) -> Response:
        m_decision = DECISION.fullmatch(path)
        if m_decision:
            if method != "GET":
                return _error(405, "dashboard.method", "GET only")
            return self._decision(*m_decision.groups())
        if method == "GET":
            if path == "/api/state.json":
                return _json(200, views.build_state(self.index, self.settings, self._now()))
            m = TASK_LOG.fullmatch(path)
            if m:
                text = views.task_log(self.index, *m.groups())
                if text is None:
                    return _error(404, "dashboard.not_found", "no such task log")
                return Response(200, text.encode(), "text/plain; charset=utf-8", _security_headers())
            m = PATH_PARTS.fullmatch(path)
            if m and m.group(2) is not None:
                return _error(405, "dashboard.method", "POST only on the write routes")
            if m:
                entry = self.index.get(m.group(1))
                if entry is None:
                    return _error(404, "dashboard.not_found", f"no run {m.group(1)}")
                return _json(200, views.build_run(entry, self.settings, self._now()))
            return _error(404, "dashboard.not_found", f"no route for {path}")
        m = PATH_PARTS.fullmatch(path)
        if not m or m.group(2) is None:
            return _error(405, "dashboard.method", "POST only on the write routes")
        return self._write(m.group(1), m.group(2), body)

    def _write(self, run_id: str, action: str, body: bytes) -> Response:
        if self.index.get(run_id) is None:
            return _error(404, "dashboard.not_found", f"no run {run_id}")
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            return _bad("the body is not JSON")
        if not isinstance(data, dict):
            return _bad("the body must be a JSON object")
        built = _build_command(run_id, action, data)
        if isinstance(built, str):
            return _bad(built)
        return _launcher_response(self.launcher([*built, "--json"]))


def _text(value: object) -> str | None:
    """Free text as one argv value. A value that starts with a dash would read as a flag, so it is refused."""
    if not isinstance(value, str) or not value.strip() or value.startswith("-"):
        return None
    return value


def _build_command(run_id: str, action: str, data: dict) -> list[str] | str:
    """The CLI argument list for a write, or the reason it is bad input. Values are passed as argv, never a shell."""
    if action == "decide":
        packet, choices, questions = data.get("packet"), data.get("choices") or {}, data.get("questions") or {}
        notes, stage = data.get("notes") or "", data.get("stage")
        if not isinstance(packet, str) or not VALUE.fullmatch(packet):
            return "packet must be the packet sha"
        if not isinstance(choices, dict) or not isinstance(questions, dict) or not isinstance(notes, str):
            return "choices and questions must be objects, notes a string"
        args = ["decide", run_id, "--packet", packet]
        for key, option in choices.items():
            if not KEY.fullmatch(str(key)) or not VALUE.fullmatch(str(option)):
                return f"choice {key!r} is not a decision id and option id"
            args.append(f"{key}={option}")
        for key, text in questions.items():
            if not KEY.fullmatch(str(key)) or _text(text) is None:
                return f"question for {key!r} must be a decision id and text"
            args += ["--question", f"{key}={text}"]
        if notes:
            if _text(notes) is None:
                return "notes must not start with a dash"
            args += ["--notes", notes]
        if stage is not None:
            if not isinstance(stage, str) or not KEY.fullmatch(stage):
                return "stage is not a stage id"
            args += ["--stage", stage]
        if data.get("by") is not None:
            if not isinstance(data["by"], str) or not VALUE.fullmatch(data["by"]):
                return "by is not a name"
            args += ["--by", data["by"]]
        return args
    if action == "note":
        task, text, deny = data.get("task"), data.get("text"), data.get("deny") or []
        if not isinstance(task, str) or not KEY.fullmatch(task):
            return "task is not a task id"
        if _text(text) is None:
            return "text must be a non-empty note that does not start with a dash"
        if not isinstance(deny, list) or not all(isinstance(d, str) and d for d in deny):
            return "deny must be a list of glob strings"
        args = ["note", f"{run_id}/{task}", text]
        for glob in deny:
            args += ["--deny", glob]
        return args
    if action == "retry":
        return ["retry", run_id]
    if action == "goto":
        stage = data.get("stage")
        if not isinstance(stage, str) or not KEY.fullmatch(stage):
            return "goto needs a stage id"
        return ["goto", run_id, stage]
    if action == "skip":
        gate, reason = data.get("gate"), _text(data.get("reason"))
        if not isinstance(gate, str) or not KEY.fullmatch(gate):
            return "skip needs a gate name"
        if reason is None:
            return "skip needs a reason"
        return ["skip", run_id, gate, "--reason", reason]
    if action == "abort":
        reason = _text(data.get("reason"))
        if reason is None:
            return "abort needs a reason"
        return ["abort", run_id, "--reason", reason]
    return f"unknown action {action}"


def _launcher_response(result: LauncherResult) -> Response:
    """The CLI's JSON document, as the page gets it: 200 when the command succeeded, 422 with its JSON error when it
    failed. A CLI that printed no JSON is a launcher failure (502)."""
    if result.doc is not None:
        return _json(200 if result.returncode == 0 else 422, result.doc)
    message = result.stderr or "the launcher printed no JSON"
    return _error(502, "launcher.failed", message)


def _security_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
