"""Plain helpers for the module 6B engine tests. Fixtures stay in conftest.py; tests import these by their own module name."""

import json
from pathlib import Path


TRIAGE_JSON = json.dumps({"schema_version": 1, "type": "chore", "workflow": "chore", "confidence": 1.0,
                          "type_source": "explicit"})


def chore_script(run_dir: Path, **overrides) -> tuple[dict, dict]:
    """A script and writes for a clean chore run: triage, the `change` task, and the `check` task. A key in
    `overrides` replaces that task's scripted attempts."""
    from factory_engine.adapters.worker.fake import ok
    work = lambda t, n: run_dir / "tasks" / t / "work" / n  # noqa: E731
    script = {"rules": [ok(work("rules", "triage.json"))], "change": [ok(work("change", "change.json"))],
              "check": [ok(work("check", "check.log"))]}
    script.update(overrides)
    writes = {"rules": {"triage.json": TRIAGE_JSON}, "change": {"change.json": "{}"}, "check": {"check.log": "ok"}}
    return script, writes
