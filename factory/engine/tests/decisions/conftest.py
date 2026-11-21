import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decisions_helpers import make_request  # noqa: E402

from factory_engine import state  # noqa: E402




@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(h))
    return h


@pytest.fixture
def run(home, tmp_path):
    """A run folder in the factory home, created the way the engine creates it."""
    return state.init_run(home, tmp_path / "repo", "github.com/acme/report", "new-color-q1w2e", make_request(),
                          branch="new-color-q1w2e", worktree=tmp_path / "wt", kit_hash="ab12")










