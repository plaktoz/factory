"""${VAR}, ${VAR:-default} and ${VAR:?message} (module 3, module 9).

Values are resolved when an attempt starts (module 9): callers pass the environment in and call this then.
An unset `:?` variable is an error with the message. A `${...}` that is not one of the three forms is an error,
so a typo never becomes a literal secret.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from .errors import FactoryError

_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:-|:\?)([^}]*))?\}")
_ANY = re.compile(r"\$\{[^}]*\}")


def is_reference(value: str) -> bool:
    """True when the whole value is one `${...}` reference (the only form allowed under `env` in committed config)."""
    m = _REF.fullmatch(value.strip())
    return m is not None


def resolve(value: str, env: Mapping[str, str], *, where: str = "value") -> str:
    def sub(m: re.Match[str]) -> str:
        name, op, arg = m.group(1), m.group(2), m.group(3)
        got = env.get(name)
        if op == ":-":
            return got if got else (arg or "")
        if op == ":?":
            if not got:
                raise FactoryError("config.invalid", f"{where}: {name} is not set: {arg or 'set it in the environment'}",
                                   hint=f"set {name}, or remove the reference")
            return got
        if got is None:
            raise FactoryError("config.invalid", f"{where}: {name} is not set",
                               hint=f"set {name}, or use ${{{name}:-default}}")
        return got

    for bad in _ANY.findall(value):
        if not _REF.fullmatch(bad):
            raise FactoryError("config.invalid", f"{where}: {bad} is not a form the factory knows",
                               hint="use ${VAR}, ${VAR:-default} or ${VAR:?message}")
    return _REF.sub(sub, value)
