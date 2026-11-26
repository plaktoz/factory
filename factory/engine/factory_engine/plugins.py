"""Plugins (module 5): enable, disable, and merge an enabled plugin's `insert` stage into the workflows it applies to.

A plugin is a folder `.factory/config/plugins/<name>/` holding one `plugin.yaml`. Nothing applies until `enable_plugin`
has recorded its folder hash in `$FACTORY_HOME/plugin-hashes.json`, keyed by repo key. The hash lives outside the repo,
so a commit cannot approve its own plugin change. The merge never edits a workflow file: `load_workflow` builds the
merged Workflow in memory (module 5, "Plugins apply in file order and never edit workflow files").
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

from . import state
from .config import Config
from .errors import FactoryError
from .types import Stage, Workflow
from .validate import validate
from .yamlio import load_yaml

PLUGINS_DIR = Path(".factory") / "config" / "plugins"
HASHES_FILE = "plugin-hashes.json"


def plugin_dir(repo: Path, name: str) -> Path:
    return repo / PLUGINS_DIR / name


def read_manifest(repo: Path, name: str) -> dict:
    """The plugin's manifest, checked against plugin.schema.json. config.invalid when it is missing or malformed."""
    folder = plugin_dir(repo, name)
    path = folder / "plugin.yaml"
    if not path.is_file():
        raise FactoryError("config.invalid", f"no plugin named {name!r}: {path} does not exist",
                           hint=f"add a folder {PLUGINS_DIR / name} with a plugin.yaml")
    doc = load_yaml(path.read_text(), file=str(path))
    if not isinstance(doc, dict):
        raise FactoryError("config.invalid", f"{path}: the top level must be a mapping",
                           hint="write the manifest keys at the top level")
    validate(doc, "plugin", file=str(path))
    return doc


SYSTEMS = {"darwin": "macos", "linux": "linux", "win32": "windows"}


def current_system() -> str:
    """The system the engine runs on, named as a plugin's `os:` names it (module 5)."""
    return SYSTEMS.get(sys.platform, sys.platform)


def check_os(manifest: dict, folder: Path, name: str) -> None:
    """A `.sh` script on a system the manifest's `os:` does not list fails here, at enable or load, not mid-run (module 5).

    A plugin with no `os:` key runs nowhere the scripts need a system, so only `.sh` scripts are checked against it.
    """
    listed = manifest.get("os")
    system = current_system()
    for script in _scripts(manifest):
        if script.endswith(".sh") and (listed is None or system not in listed):
            raise FactoryError("config.invalid",
                               f"{name}: script {script} is a .sh script, and this system ({system}) is not in its os: {listed or '[]'}",
                               hint=f"list {system} under os: in plugin.yaml, or drop the .sh script")


def _scripts(manifest: dict) -> list[str]:
    found = []
    for hook in manifest.get("hooks") or []:
        found.append((hook.get("run") or {}).get("script"))
    for task in (manifest.get("insert") or {}).get("stage", {}).get("tasks") or []:
        found.append((task.get("run") or {}).get("script"))
    return [s for s in found if s]


def check_requires(manifest: dict, repo: Path, name: str) -> None:
    """Each skill the manifest requires must be in skills.lock (module 5 Safety, owner decision 2026-11-24)."""
    from . import skills

    wanted = (manifest.get("requires") or {}).get("skills") or []
    if not wanted:
        return
    locked = {n for names in (skills.lock_allow(repo) or {}).values() for n in (names or [])}
    missing = [s for s in wanted if s not in locked]
    if missing:
        raise FactoryError("config.invalid", f"{name}: requires skill {missing[0]!r}, which is not in skills.lock",
                           hint=f"pin {missing[0]!r} in factory/skills.lock, or remove it from requires.skills")


def _hashes_path(home: Path) -> Path:
    return home / HASHES_FILE


class HashesUnreadable(FactoryError):
    """plugin-hashes.json exists but cannot be read as the recorded mapping (module 5 Safety, owner decision 2026-11-24).

    A FactoryError, so enable and disable report it in the shared shape. `plugin_status` turns it into an off-state with
    this message as the reason, so a run still answers the reason rather than failing unexplained.
    """

    def __init__(self, message: str):
        super().__init__("config.invalid", message, hint="delete plugin-hashes.json and enable each plugin again")


def _read_hashes(home: Path, repo_key: str) -> dict[str, str]:
    path = _hashes_path(home)
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text())
        return dict(doc.get(repo_key, {})) if isinstance(doc, dict) else _unreadable(path, "is not a mapping")
    except (OSError, ValueError, TypeError) as e:
        return _unreadable(path, f"cannot be read: {e}")


def _unreadable(path: Path, why: str) -> dict[str, str]:
    raise HashesUnreadable(f"{path.name} {why}")


def plugin_status(repo: Path, cfg: Config, name: str) -> dict:
    """Whether a plugin applies to runs now, and the reason when it does not: `{"state": "on"|"off", "reason": str}`.

    A plugin is off when it is not enabled, when its folder changed since enable (the reason names the first changed
    file), when its folder is gone, or when plugin-hashes.json cannot be read (every plugin is then off, and the reason
    names the file). The run's summary shows the reason (module 5).
    """
    try:
        hashes = _read_hashes(state.factory_home(), state.repo_key(repo, cfg))
    except HashesUnreadable as e:
        return {"state": "off", "reason": f"plugin {name} is off: {e}; enable it again to record its hash"}
    if name not in hashes:
        return {"state": "off", "reason": f"plugin {name} is not enabled"}
    folder = plugin_dir(repo, name)
    if not folder.is_dir():
        return {"state": "off", "reason": f"plugin {name} is off: its folder {folder} is gone"}
    current = _file_hashes(folder)
    recorded = hashes[name]
    if current != recorded:
        changed = _first_changed(recorded, current)
        return {"state": "off", "reason": f"plugin {name} is off: {changed} changed after enable; enable it again to review the change"}
    return {"state": "on", "reason": ""}


def _file_hashes(folder: Path) -> dict[str, str]:
    """One hash per file under the folder, keyed by its path from the folder."""
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def _first_changed(recorded: str | dict, current: dict[str, str]) -> str:
    """The first file that differs, by path. A hash recorded as one folder digest (an older record) names no file."""
    if not isinstance(recorded, dict):
        return "the plugin folder"
    for path in sorted(set(recorded) | set(current)):
        if recorded.get(path) != current.get(path):
            return path
    return "the plugin folder"


def _write_hashes(home: Path, repo_key: str, hashes: dict[str, str]) -> None:
    path = _hashes_path(home)
    doc = json.loads(path.read_text()) if path.is_file() else {}
    doc[repo_key] = hashes
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


def enable_plugin(repo: Path, cfg: Config, name: str) -> Workflow:
    """Check the plugin, record its folder hash, and return the merged workflow it gives its first `applies_to` workflow.

    The base workflow is loaded without plugins, so enabling never depends on what is already enabled. The result is the
    merged workflow to show. Raises config.invalid, and records nothing, when the plugin does not merge cleanly.
    """
    from .workflow import load_workflow  # local: workflow.py calls back into this module when it loads

    manifest = read_manifest(repo, name)
    applies = list(manifest["applies_to"])
    if not applies:
        raise FactoryError("config.invalid", f"{name}: applies_to names no workflow", hint="list at least one workflow name")
    check_os(manifest, plugin_dir(repo, name), name)
    check_requires(manifest, repo, name)
    check_run_tasks(manifest, name)
    shown = merge_insert(load_workflow(repo, cfg, applies[0], apply_plugins=False), manifest, name)
    home, key = state.factory_home(), state.repo_key(repo, cfg)
    hashes = _read_hashes(home, key)
    hashes[name] = _file_hashes(plugin_dir(repo, name))
    _write_hashes(home, key, hashes)
    return shown


def disable_plugin(repo: Path, name: str) -> None:
    """Forget the plugin's hash, so it no longer applies to any run."""
    from .loadcfg import load_config

    home, key = state.factory_home(), state.repo_key(repo, load_config(repo))
    hashes = _read_hashes(home, key)
    hashes.pop(name, None)
    _write_hashes(home, key, hashes)


def applied_to(repo: Path, cfg: Config, workflow: str) -> list[dict]:
    """The enabled plugins whose `applies_to` names this workflow, in name order, with their manifests.

    A plugin whose folder no longer matches its recorded hash is left out (module 5, "the plugin is switched off until
    enabled again"). Its manifest is read once here, so the merge sees the reviewed content.
    """
    try:
        hashes = _read_hashes(state.factory_home(), state.repo_key(repo, cfg))
    except HashesUnreadable:
        return []  # every plugin is off for this run; plugin_status gives the reason
    out = []
    for name in sorted(hashes):
        if plugin_status(repo, cfg, name)["state"] != "on":
            continue
        manifest = read_manifest(repo, name)
        if workflow in manifest["applies_to"]:
            out.append({"name": name, "manifest": manifest})
    return out


def check_run_tasks(manifest: dict, name: str) -> None:
    """A plugin task sets exactly one of `cmd` and `run` (`skill` is not allowed for a plugin deterministic task here).

    Module 5 says a task sets exactly one of skill, cmd or run. A `run` task with a `cmd` beside it is refused at enable.
    """
    for task in (manifest.get("insert") or {}).get("stage", {}).get("tasks") or []:
        if "run" in task and "cmd" in task:
            raise FactoryError("config.invalid", f"{name}: task {task.get('id')!r} sets both run and cmd",
                               hint="keep one: run for a plugin script or function, cmd for a command")


def merge_insert(wf: Workflow, manifest: dict, name: str) -> Workflow:
    """`wf` with the plugin's `insert.stage` placed after or before its anchor, and the chain joined around it.

    `after` puts the stage right after the anchor, and the stage that followed the anchor in the list waits for it
    (owner decision D4, 2026-11-22). `before` puts it right before the anchor, and the anchor waits for it. A plugin
    author lists no order: the loader rewrites the neighbour's `needs`.
    """
    from .workflow import _parse_stage  # the workflow parser builds every stage the same way

    insert = manifest["insert"]
    anchor_key = "after" if "after" in insert else "before"
    anchor = insert[anchor_key]
    ids = [s.id for s in wf.stages]
    if anchor not in ids:
        raise FactoryError("config.invalid", f"{name}: insert.{anchor_key} names {anchor!r}, which is not a stage of {wf.name}",
                           hint="stages: " + ", ".join(ids))
    spec = dict(insert["stage"])
    if anchor_key == "after":
        spec["needs"] = [anchor]
    inserted = replace(_parse_stage(spec, wf.defaults), source=f"plugin:{name}")
    pos = ids.index(anchor)
    if anchor_key == "after":
        stages = wf.stages[:pos + 1] + [inserted]
        if pos + 1 < len(wf.stages):  # the stage that followed the anchor now waits for the inserted one
            nxt = wf.stages[pos + 1]
            stages += [replace(nxt, needs=[*nxt.needs, inserted.id]), *wf.stages[pos + 2:]]
    else:
        stages = wf.stages[:pos] + [inserted] + [replace(wf.stages[pos], needs=[*wf.stages[pos].needs, inserted.id]), *wf.stages[pos + 1:]]
    return replace(wf, stages=stages)
