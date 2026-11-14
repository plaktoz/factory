"""validate(obj, schema) against factory/schemas (module 3). A failure raises config.invalid with the fix."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from .errors import FactoryError

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


@lru_cache(maxsize=None)
def _schema(name: str) -> dict:
    path = SCHEMA_DIR / f"{name}.schema.json"
    if not path.is_file():
        raise FactoryError("config.invalid", f"no schema named {name!r} in {SCHEMA_DIR}",
                           hint="the schema must be in factory/schemas/")
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def _registry() -> Registry:
    """Every schema in the folder by its file name, so a relative $ref such as decision -> packet.schema.json resolves."""
    resources = [(f.name, Resource.from_contents(json.loads(f.read_text()), default_specification=DRAFT202012))
                 for f in sorted(SCHEMA_DIR.glob("*.schema.json"))]
    return Registry().with_resources(resources)


def validate(obj: dict, schema: str, *, file: str = "<input>") -> None:
    """Raise config.invalid naming the first failing path and the file."""
    validator = jsonschema.Draft202012Validator(_schema(schema), registry=_registry())
    errors = sorted(validator.iter_errors(obj), key=lambda e: list(e.absolute_path))
    if not errors:
        return
    e = errors[0]
    path = ".".join(str(p) for p in e.absolute_path) or "(top level)"
    raise FactoryError("config.invalid", f"{file}: {path}: {e.message}",
                       hint=f"fix {path} in {file} to match factory/schemas/{schema}.schema.json")
