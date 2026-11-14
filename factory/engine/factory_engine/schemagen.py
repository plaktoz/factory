"""Build JSON Schemas for the dataclasses written to state files (section 18, W0.4).

The schemas in factory/schemas/ are the source of truth for files on disk. This module generates the ones
backed by a shared dataclass, so a field change in types.py and its schema cannot drift apart:
tests/shared/test_schemas.py regenerates them and compares with the committed files.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import types as pytypes
import typing
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

from . import types as T

SCHEMA_VERSION = 1
# file schema name -> dataclass written to it
FILE_TYPES: dict[str, type] = {
    "request": T.Request,
    "run": T.Run,
    "task": T.TaskState,
    "usage": T.UsageRecord,
    "event": T.Event,
}
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def _type_schema(tp: Any, defs: dict[str, Any]) -> dict[str, Any]:
    origin = get_origin(tp)
    if tp is type(None):
        return {"type": "null"}
    if tp is str:
        return {"type": "string"}
    if tp is bool:
        return {"type": "boolean"}
    if tp is int:
        return {"type": "integer"}
    if tp is float:
        return {"type": "number"}
    if tp is dict or origin is dict:
        args = get_args(tp)
        if args:
            return {"type": "object", "additionalProperties": _type_schema(args[1], defs)}
        return {"type": "object"}
    if tp is Path:
        return {"type": "string"}
    if origin is Literal:
        return {"enum": list(get_args(tp))}
    if origin is list:
        (item,) = get_args(tp)
        return {"type": "array", "items": _type_schema(item, defs)}
    if origin is tuple:
        return {"type": "array", "prefixItems": [_type_schema(a, defs) for a in get_args(tp)],
                "minItems": len(get_args(tp)), "maxItems": len(get_args(tp))}
    if origin is Union or origin is pytypes.UnionType:
        return {"anyOf": [_type_schema(a, defs) for a in get_args(tp)]}
    if dataclasses.is_dataclass(tp):
        name = tp.__name__
        if name not in defs:
            defs[name] = {}  # placeholder against recursion
            defs[name] = _object_schema(tp, defs)
        return {"$ref": f"#/$defs/{name}"}
    raise TypeError(f"no JSON Schema rule for {tp!r}")


def _object_schema(cls: type, defs: dict[str, Any]) -> dict[str, Any]:
    hints = typing.get_type_hints(cls)
    props = {f.name: _type_schema(hints[f.name], defs) for f in dataclasses.fields(cls)}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def build(name: str) -> dict[str, Any]:
    cls = FILE_TYPES[name]
    defs: dict[str, Any] = {}
    body = _object_schema(cls, defs)
    body["properties"] = {"schema_version": {"const": SCHEMA_VERSION}, **body["properties"]}
    body["required"] = ["schema_version", *body["required"]]
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"factory/{name}.schema.json",
        "title": name,
        "description": f"Generated from factory_engine.types.{cls.__name__} by factory_engine.schemagen; do not edit by hand.",
        **body,
    }
    if defs:
        schema["$defs"] = dict(sorted(defs.items()))
    return schema


def render(name: str) -> str:
    return json.dumps(build(name), indent=2) + "\n"


def write_all(out: Path = SCHEMA_DIR) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in FILE_TYPES:
        p = out / f"{name}.schema.json"
        p.write_text(render(name))
        paths.append(p)
    return paths


if __name__ == "__main__":
    for p in write_all():
        print(p)
    sys.exit(0)
