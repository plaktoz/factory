"""The one Config type (section 18). Module 3 builds it with load_config; wave 0 defines only the shape."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Config:
    """machine: keys of the per-machine file. repo: keys of factory.yaml, or None when loaded with repo=None.

    The keys of each part are defined by the schemas in factory/schemas (module 3), not here.
    """

    machine: dict
    repo: dict | None
