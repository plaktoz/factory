import re

import pytest

from factory_engine import errors
from factory_engine.errors import CATALOGUE, ERROR_KINDS, FactoryError


def test_five_error_kinds():
    assert ERROR_KINDS == ("fail_fast", "transient", "task_retry", "rework", "human")


def test_exit_codes_match_section_18():
    assert (errors.EXIT_OK, errors.EXIT_FAILED, errors.EXIT_INVALID,
            errors.EXIT_WAITING_HUMAN, errors.EXIT_BLOCKED, errors.EXIT_LOCKED) == (0, 1, 2, 3, 4, 5)


def test_every_catalogue_code_is_namespaced_with_a_known_kind_and_a_hint():
    for code, entry in CATALOGUE.items():
        assert re.fullmatch(r"[a-z]+\.[a-z_]+", code), code
        assert entry.kind in ERROR_KINDS
        assert entry.hint


def test_one_code_per_sandbox_failure_type():
    sandbox = {c for c in CATALOGUE if c.startswith("sandbox.")}
    assert sandbox == {
        "sandbox.unavailable", "sandbox.settings_invalid", "sandbox.settings_unreadable",
        "sandbox.settings_unparseable", "sandbox.srt_missing", "sandbox.node_old", "sandbox.canary_open",
    }


def test_error_takes_kind_and_hint_from_the_catalogue():
    e = FactoryError("config.invalid", "factory.yaml line 3: cmd is a string")
    assert (e.code, e.kind, e.hint) == ("config.invalid", "fail_fast", CATALOGUE["config.invalid"].hint)
    assert e.message == "factory.yaml line 3: cmd is a string"
    assert e.exit_code == 2


def test_hint_and_kind_can_be_overridden():
    e = FactoryError("git.hook_failed", "pre-commit failed", hint="run make lint", kind="rework")
    assert (e.hint, e.kind) == ("run make lint", "rework")


def test_unlisted_code_is_refused():
    with pytest.raises(ValueError, match="not in the catalogue"):
        FactoryError("made.up", "x")


def test_unknown_kind_is_refused():
    with pytest.raises(ValueError, match="unknown error kind"):
        FactoryError("config.invalid", "x", kind="maybe")  # type: ignore[arg-type]


def test_locked_exits_5_and_human_exits_3():
    assert FactoryError("state.locked", "held").exit_code == 5
    assert FactoryError("sandbox.unavailable", "no sandbox").exit_code == 3


def test_json_shape():
    assert FactoryError("config.invalid", "bad").to_json() == {
        "ok": False, "code": "config.invalid", "message": "bad",
        "hint": CATALOGUE["config.invalid"].hint, "data": {},
    }
