"""The engine tests' fixtures, loaded by path under a unique module name, and their helpers from `engine_helpers`.

`tests/engine/conftest.py` cannot be imported as `conftest` when several test folders run in one session, because
pytest keeps one module called `conftest` and another folder's file gets there first. Loading it by path avoids that.
"""

import importlib.util
import sys
from pathlib import Path

_ENGINE_TESTS = Path(__file__).resolve().parents[1] / "engine"
for extra in (_ENGINE_TESTS, _ENGINE_TESTS.parent / "gitops"):  # the engine conftest imports gitutil from its folder
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

_spec = importlib.util.spec_from_file_location("engine_tests_conftest", _ENGINE_TESTS / "conftest.py")
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

from engine_helpers import TRIAGE_JSON, chore_script  # noqa: E402,F401
