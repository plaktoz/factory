"""Optional live smoke for the Codex adapter (module 9, P2-1). Runs only when FACTORY_LIVE=1, `codex` is on PATH, and
OPENAI_API_KEY is set.

It makes one short model call through the real `codex exec`, wrapped in srt with the attempt's own settings. It checks
what the recorded stub cannot: the real event stream parses, the tokens come from the real turn.completed usage, and the
worker ends ok. Each run costs one short call, so CI never spends tokens.
"""

import os
import shutil

import pytest

from factory_engine.adapters.worker.codex import CodexAdapter
from factory_engine.types import HelperPolicy

from workers_helpers import harness

LIVE = os.environ.get("FACTORY_LIVE") == "1" and shutil.which("codex") is not None and bool(os.environ.get("OPENAI_API_KEY"))
pytestmark = pytest.mark.skipif(not LIVE, reason="set FACTORY_LIVE=1, put codex on PATH and set OPENAI_API_KEY")


def test_one_real_codex_attempt_parses_the_real_event_stream(tmp_path, worktree, task_dir, make_ctx, factory_home):
    machine = {k: os.environ[k] for k in ("PATH", "HOME", "OPENAI_API_KEY", "OPENAI_BASE_URL") if os.environ.get(k)}
    conf = harness("codex", {k: f"${{{k}}}" for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL") if k in machine})
    ctx = make_ctx(helpers=HelperPolicy("off", 0, [], None))
    ad = CodexAdapter(machine)
    check = ad.check(conf)
    assert check.ok, check.detail
    handle = ad.start(ctx, conf, tmp_path / "worker.log")
    result = ad.wait(handle, 240)
    log = (tmp_path / "worker.log").read_text()
    assert result.exit == "ok", (result, log[-800:])
    assert result.input_tokens is not None and result.output_tokens is not None
    assert result.models_observed == []
