"""types.py must have exactly the fields the spec lists, in the same order (W0.6, first part)."""

import dataclasses

import pytest

from factory_engine import types as T

from spec_blocks import spec_fields

SPEC = spec_fields()
# Classes the spec shows only in prose, or that are not plain dataclasses.
NOT_COMPARED = {"FactoryError", "Clock", "Config"}


def test_spec_parser_found_the_known_classes():
    assert {"Run", "Request", "GateSpec", "RunSpec", "UsageRecord", "Workflow", "Stage", "TaskSpec"} <= set(SPEC)


@pytest.mark.parametrize("name", sorted(n for n in SPEC if n not in NOT_COMPARED))
def test_fields_match_spec(name):
    cls = getattr(T, name, None)
    assert cls is not None, f"spec defines {name} but types.py does not"
    assert dataclasses.is_dataclass(cls), f"{name} is not a dataclass"
    assert [f.name for f in dataclasses.fields(cls)] == SPEC[name]


def test_every_dataclass_in_types_is_in_the_spec_or_listed():
    in_code = {n for n, c in vars(T).items() if isinstance(c, type) and dataclasses.is_dataclass(c) and c.__module__ == T.__name__}
    # Policy and Defaults are given in module 5's YAML, not as a class in a code block.
    assert in_code - set(SPEC) <= {"Policy", "Defaults"}


def test_frozen_runref():
    ref = T.RunRef(repo=__import__("pathlib").Path("."), repo_key="k", run_id="r", run_dir=__import__("pathlib").Path("."))
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.run_id = "x"  # type: ignore[misc]
