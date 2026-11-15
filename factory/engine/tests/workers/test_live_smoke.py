"""Optional live smoke for the Claude adapter (module 9). Runs only when FACTORY_LIVE=1 and `claude` is on PATH.

It makes one short model call through the real CLI, with the attempt's own flags and sandbox settings. It checks what
the stub cannot: the real result shape parses, the tokens come from the real result, and the model names come from the
real modelUsage keys. Each run costs one short call. It is skipped otherwise, so CI never spends tokens.
"""

import os
import shutil

import pytest

from factory_engine.adapters.worker import claude as C
from factory_engine.adapters.worker.claude import ClaudeAdapter
from factory_engine.types import HelperPolicy

from conftest import harness

LIVE = os.environ.get("FACTORY_LIVE") == "1" and shutil.which("claude") is not None
pytestmark = pytest.mark.skipif(not LIVE, reason="set FACTORY_LIVE=1 and put claude on PATH to run the live smoke")

ENV_NAMES = ("PATH", "HOME", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL")


def test_one_real_attempt_parses_the_real_result(tmp_path, worktree, task_dir, make_ctx, factory_home):
    machine = {k: os.environ[k] for k in ENV_NAMES if os.environ.get(k)}
    conf = harness("claude", {k: f"${{{k}}}" for k in machine if k.startswith("ANTHROPIC_")})
    ctx = make_ctx(helpers=HelperPolicy("off", 0, [], None))
    ad = ClaudeAdapter(machine)
    check = ad.check(conf)
    assert check.ok, check.detail
    handle = ad.start(ctx, conf, tmp_path / "worker.log")
    result = ad.wait(handle, 240)
    assert result.exit == "ok", (result, (tmp_path / "worker.log").read_text()[-500:])
    assert result.models_observed, "the real result reports at least one modelUsage key"
    assert result.input_tokens is not None and result.output_tokens is not None
