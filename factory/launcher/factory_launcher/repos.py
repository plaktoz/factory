"""The repos this machine serves: the `repos` list in $FACTORY_HOME/config.yaml (Appendix A, step 5).

`factory init --github` adds a repo here, and `tick --all-repos` syncs every repo listed, so a new repo is picked up
before it has a run. The file is edited by line, so its comments and other keys stay as they are.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from factory_engine.errors import FactoryError


def _file(home: Path) -> Path:
    return home / "config.yaml"


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    doc = yaml.safe_load(path.read_text()) or {}
    if not isinstance(doc, dict):
        raise FactoryError("config.invalid", f"{path}: the top level must be a mapping", hint="write key: value pairs")
    return doc


def registered(home: Path) -> list[Path]:
    """The listed repos, in file order. An entry that is not a string is skipped."""
    listed = _load(_file(home)).get("repos") or []
    return [Path(r) for r in listed if isinstance(r, str)]


def register(home: Path, repo: Path) -> bool:
    """Add `repo` to `repos` unless it is listed. Returns True when the file changed."""
    path = _file(home)
    repo = Path(repo).resolve()
    doc = _load(path)
    current = [r for r in (doc.get("repos") or []) if isinstance(r, str)]
    if str(repo) in current:
        return False
    new_list = yaml.safe_dump({"repos": [*current, str(repo)]}, default_flow_style=False, sort_keys=False)
    lines = path.read_text().splitlines(keepends=True) if path.is_file() else []
    out, skipping, replaced = [], False, False
    for line in lines:
        if skipping and (line.startswith((" ", "\t", "-")) or not line.strip()):
            continue
        skipping = False
        if line.startswith("repos:"):
            out.append(new_list)
            skipping, replaced = True, True
            continue
        out.append(line)
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append(new_list)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(out))
    os.replace(tmp, path)
    return True
