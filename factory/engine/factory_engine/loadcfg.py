"""load_config(repo, env) and resolve_harness (module 3, module 9).

Machine file: ~/.factory/config.yaml (or $FACTORY_HOME/config.yaml). Repo file: .factory/config/factory.yaml.
Config(machine, repo) is the one configuration type (section 18). With repo=None, .repo is None.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .adapters.worker.base import HarnessConfig
from .config import Config
from .errors import FactoryError
from .interpolate import resolve
from .repo_rules import check_cleanup_check, refuse_literal_env
from .validate import validate
from .yamlio import load_yaml

MACHINE_DEFAULTS: dict[str, Any] = {"max_workers": 6}
REPO_DEFAULTS: dict[str, Any] = {"concurrency": 4, "infra_wait_hours": 6, "serialize_overlapping_runs": False}


def factory_home(env: Mapping[str, str] = os.environ) -> Path:
    return Path(env.get("FACTORY_HOME") or Path.home() / ".factory")


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    doc = load_yaml(path.read_text(), file=str(path))
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        raise FactoryError("config.invalid", f"{path}: the top level must be a mapping", hint="write key: value pairs")
    return doc


def load_config(repo: Path | None, *, env: Mapping[str, str] = os.environ) -> Config:
    home = factory_home(env)
    machine_file = home / "config.yaml"
    machine = {**MACHINE_DEFAULTS, **_read(machine_file)}
    # The machine file has no JSON Schema in module 3's list, so it is read but not schema-checked here.
    # Its keys are checked where they are used (harnesses in resolve_harness; the rest in their modules).
    if env.get("FACTORY_WORKTREE_ROOT"):
        machine["worktree_root"] = env["FACTORY_WORKTREE_ROOT"]
    if repo is None:
        return Config(machine=machine, repo=None)

    repo_file = repo / ".factory" / "config" / "factory.yaml"
    raw = _read(repo_file)
    if repo_file.is_file():
        validate(raw, "factory-config", file=str(repo_file))
        refuse_literal_env(_flatten_env(raw), file=str(repo_file))
    check_cleanup_check(raw.get("cleanup_check"), file=str(repo_file))
    rep = {**REPO_DEFAULTS, **raw}
    return Config(machine=machine, repo=rep)


def _flatten_env(doc: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for harness in (doc.get("harnesses") or {}).values() if isinstance(doc.get("harnesses"), dict) else []:
        out.update({k: str(v) for k, v in (harness.get("env") or {}).items()})
    return out


def resolve_harness(cfg: Config, harness: str, *, env: Mapping[str, str] = os.environ, stage_model: str | None = None,
                    task_model: str | None = None) -> HarnessConfig:
    """command, model (None when no model is set), args and the minimal env with ${...} resolved now.

    Model precedence (module 9): task, then stage routing, then harness default, then None. A model that stays
    None sends no --model flag; the harness then reads ANTHROPIC_MODEL from the environment (module 9)."""
    harnesses = cfg.machine.get("harnesses") or {}
    if harness not in harnesses:
        raise FactoryError("config.invalid", f"harness {harness!r} is not in the machine file",
                           hint=f"add harnesses.{harness} to ~/.factory/config.yaml")
    if harness not in ("claude", "codex"):
        raise FactoryError("config.invalid", f"harness {harness!r}: the accepted harnesses are claude and codex",
                           hint="set harness: claude or harness: codex")
    h = harnesses[harness]
    raw_env = h.get("env") or {}
    resolved_env = {k: resolve(str(v), env, where=f"harnesses.{harness}.env.{k}") for k, v in raw_env.items()}
    model = task_model or stage_model or h.get("model")
    model = resolve(model, env, where="model") if model else None
    if model == "":
        model = None
    return HarnessConfig(command=h.get("command", harness), model=model, args=list(h.get("args") or []), env=resolved_env)
