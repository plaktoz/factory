"""Runs a plugin's Python function in its own process (module 9, module 5).

`python -m factory_engine.plugin_runner <plugin dir> <module:function>`. The task context arrives as JSON on stdin
(FACTORY_RUN_ID, FACTORY_STAGE, FACTORY_TASK_ID, FACTORY_WORKTREE, FACTORY_TASK_DIR). The function's return value is
printed as JSON on stdout. Exit codes: 0 passed, 1 the check found a problem, 2 the task itself failed.

A function that raises or calls `sys.exit` is a task error (exit 2), and so is a result that cannot be written as
JSON. So is anything that stops the plugin from loading: a module or function that does not exist, a syntax error,
any other error raised while the module is imported, and a `sys.exit` at import time.

A result dict says pass or fail by `status` (`passed`, `check_failed`, anything else is a task error). When it has no
`status`, `passed` decides: true is exit 0 and false is exit 1.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if len(args) != 2 or ":" not in args[1]:
        print(json.dumps({"error": "usage: plugin_runner <plugin dir> <module:function>"}))
        return 2
    plugin_dir, target = Path(args[0]).resolve(), args[1]
    module_name, func_name = target.split(":", 1)
    sys.path.insert(0, str(plugin_dir))
    try:
        context = json.loads(sys.stdin.read() or "{}")
    except ValueError as e:
        print(json.dumps({"error": f"stdin is not JSON: {e}"}))
        return 2
    try:
        func = getattr(importlib.import_module(module_name), func_name)
    except (Exception, SystemExit) as e:  # a plugin that cannot be loaded is a task error, whatever stopped it
        print(json.dumps({"error": f"{target} cannot be imported: {type(e).__name__}: {e}"}))
        return 2
    try:
        result = func(context)
    except (Exception, SystemExit) as e:  # a plugin function that raises or exits is a task error
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        return 2
    if isinstance(result, bool):
        code = 0 if result else 1
        print(json.dumps({"passed": result}))
        return code
    if not isinstance(result, dict):
        print(json.dumps({"error": "a plugin function returns a dict"}))
        return 2
    try:
        line = json.dumps(result)
    except (TypeError, ValueError) as e:
        print(json.dumps({"error": f"result cannot be written as JSON: {e}"}))
        return 2
    print(line)
    status = result.get("status")
    if status is None:
        status = "passed" if result.get("passed", True) is True else "check_failed"
    if status == "passed":
        return 0
    if status == "check_failed":
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
