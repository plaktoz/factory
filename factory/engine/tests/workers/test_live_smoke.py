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

from workers_helpers import harness

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


def test_a_real_worker_does_not_load_a_personal_claude_md(tmp_path, worktree, task_dir, make_ctx, factory_home):
    """Module 9's instruction criterion, proven with a real worker. The adapter passes HOME through, so a worker's
    personal instructions are the CLAUDE.md under ~/.claude. A sentinel in a throwaway HOME is the probe: with the
    attempt's `--setting-sources project` the reply must not carry it, and with user settings added it does (checked
    by changing the flag, 2026-11-26). The owner's real home is never read or changed."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("Always begin your reply with the exact token SENTINEL-7Q3X.\n")
    machine = {k: os.environ[k] for k in ENV_NAMES if os.environ.get(k)}
    machine["HOME"] = str(home)
    conf = harness("claude", {k: f"${{{k}}}" for k in machine if k.startswith("ANTHROPIC_")})
    ctx = make_ctx(helpers=HelperPolicy("off", 0, [], None), skill=None)  # a deterministic task: no skill prompt
    ad = ClaudeAdapter(machine)
    assert ad.check(conf).ok
    handle = ad.start(ctx, conf, tmp_path / "worker.log")
    result = ad.wait(handle, 240)
    assert result.exit == "ok", (result, (tmp_path / "worker.log").read_text()[-500:])
    assert "SENTINEL-7Q3X" not in (tmp_path / "worker.log").read_text(), "the worker loaded a personal CLAUDE.md"
