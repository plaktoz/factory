"""The one YAML loader for every file the factory reads (module 3, YAML 1.2 booleans).

Plain yaml.safe_load reads `off`, `on`, `yes` and `no` as booleans. The spec's own examples use `mode: off`
and a hook key `on:`, so only `true` and `false` are booleans here. Never runs code.
"""

from __future__ import annotations

import re
from typing import Any

import yaml
from yaml.resolver import Resolver

from .errors import FactoryError


class FactoryLoader(yaml.SafeLoader):
    """SafeLoader with the YAML 1.1 boolean words removed, leaving true and false."""


FactoryLoader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"]
    for k, v in Resolver.yaml_implicit_resolvers.items()
}
FactoryLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false|True|TRUE|False|FALSE)$"), list("tTfF"))


def load_yaml(text: str, *, file: str = "<input>") -> Any:
    """Parse YAML. A parse error becomes config.invalid with the file and line."""
    try:
        return yaml.load(text, Loader=FactoryLoader)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 1}" if mark is not None else "unknown line"
        raise FactoryError("config.invalid", f"{file}: invalid YAML at {where}: {getattr(e, 'problem', e)}",
                           hint="fix the YAML syntax at that line") from e
