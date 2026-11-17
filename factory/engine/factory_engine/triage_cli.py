"""`factory triage`: the `rules` task's command (module 4, the shared _triage stage).

The engine copies the run's request.json into this task's folder before the command starts (ADR
2026-11-17-factory-triage-reads-its-request-from-the-task-folder), because the sandbox denies reads of the factory home.
The command reads that copy, applies triage_rules, and writes triage.json beside it. It takes no arguments and reads
no run, config or repo, so the sandbox's read rules are enough for it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import triage
from .errors import FactoryError
from .types import Request, Source

TASK_DIR_VAR = "FACTORY_TASK_DIR"
REQUEST_FILE = "request.json"
TRIAGE_FILE = "triage.json"
SCHEMA_VERSION = 1


def read_request(path: Path) -> Request:
    """The Request a state file holds, read back from request.json (the fields state.init_run writes)."""
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise FactoryError("config.invalid", f"{path} is not readable JSON: {e}",
                           hint="the engine copies request.json into the task folder before the command runs") from e
    src = doc.get("source") or {}
    source = Source(type=src.get("type", "cli"), ref=src.get("ref", ""), title=src.get("title", ""),
                    body=src.get("body", ""), labels=list(src.get("labels") or []), author=src.get("author"),
                    files=[Path(f) for f in (src.get("files") or [])])
    return Request(request_id=doc.get("request_id", ""), source=source, body_sha=doc.get("body_sha", ""),
                   repo=doc.get("repo", ""), title=doc.get("title", source.title), type=doc.get("type"),
                   type_source=doc.get("type_source"), priority=doc.get("priority"),
                   acceptance=list(doc.get("acceptance") or []))


def run_triage() -> int:
    """Read the request in the task folder, decide the type by rules, and write triage.json. Returns 0.

    A request no rule decides writes a null type and workflow with confidence 0, which the classify task fills in (the
    `when` on that task runs it below 0.8), so the command still exits 0 and the gate sees a file."""
    raw = os.environ.get(TASK_DIR_VAR)
    if not raw:
        raise FactoryError("config.invalid", f"{TASK_DIR_VAR} is not set",
                           hint="factory triage runs as a task of the triage stage; the engine sets the folder")
    task = Path(raw)
    request_path = task / REQUEST_FILE
    if not request_path.is_file():
        raise FactoryError("config.invalid", f"no {REQUEST_FILE} in {task}",
                           hint="the engine copies request.json into the task folder before the command runs")
    request = read_request(request_path)
    # triage_rules does not read its config, so the command passes none; it stays out of the sandbox's reach.
    decided = triage.triage_rules(request, cfg=None)  # type: ignore[arg-type]
    doc = {"schema_version": SCHEMA_VERSION, "type": decided.type, "workflow": decided.workflow,
           "confidence": decided.confidence, "type_source": decided.type_source}
    (task / TRIAGE_FILE).write_text(json.dumps(doc, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_triage())
