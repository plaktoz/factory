"""Machine launcher: the dashboard server (module 15). Module 16 adds the machine commands here.

Importing this package checks that the interpreter can import the engine's runtime dependencies (the list in
factory/engine/pyproject.toml). Every launcher entry point runs this first, so a Python without them stops here with
one named error and exit 2, not a traceback from inside the engine. With --json the error is the shared JSON shape."""

import json
import sys

from factory_engine.errors import FactoryError

# module name -> the package that provides it (factory/engine/pyproject.toml, dependencies)
RUNTIME_DEPENDENCIES = {"yaml": "PyYAML", "jsonschema": "jsonschema"}


def _check_runtime_dependencies() -> None:
    for module, package in RUNTIME_DEPENDENCIES.items():
        try:
            __import__(module)
        except ImportError:
            e = FactoryError("config.invalid", f"{sys.executable} cannot import {module} ({package})",
                             hint="install the factory-engine dependencies: pip install pyyaml jsonschema, "
                                  "or use `uv tool install` on factory/launcher")
            if "--json" in sys.argv[1:]:
                print(json.dumps({"ok": False, "code": e.code, "message": e.message, "hint": e.hint, "data": {}}))
            else:
                print(f"{e.code}: {e.message}\nhint: {e.hint}", file=sys.stderr)
            raise SystemExit(e.exit_code)


_check_runtime_dependencies()
