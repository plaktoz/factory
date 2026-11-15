"""The gate check registry (module 8): check name -> "module:function", imported only when a gate runs.

Each function takes (GateSpec, GateContext) and returns a GateResult. A check whose module is not built yet fails
fast with config.invalid, so a workflow that names it stops before any work starts.
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable

from .errors import FactoryError
from .types import GateContext, GateResult, GateSpec

CHECKS: dict[str, str] = {
    "scope-diff": "gitops:check_scope_diff",
    "helpers-ledger": "prompt:check_helpers_ledger",
    "type-resolved": "triage:check_type_resolved",
    "decision-approved": "decisions:check_approved",
    "packet-hash-matches": "decisions:check_packet_hash",
    "no-blocking-findings": "gates:check_findings",
    "evidence-cites-code": "gates:check_evidence",
    "every-claim-has-source": "gates:check_sources",
    "lint-clean": "toolchains:check_lint_clean",
    "build-matches-stack": "decisions:check_build_stack",
}

CheckFn = Callable[[GateSpec, GateContext], GateResult]


def resolve(name: str) -> CheckFn:
    ref = CHECKS.get(name)
    if ref is None:
        raise FactoryError("config.invalid", f"no check named {name!r}",
                           hint="use one of: " + ", ".join(sorted(CHECKS)))
    module, _, func = ref.partition(":")
    if importlib.util.find_spec(f"{__package__}.{module}") is None:
        raise FactoryError("config.invalid", f"check {name!r} lives in {module}.py, which is not built yet",
                           hint=f"build the module that owns {module}.py before its gate runs")
    mod = importlib.import_module(f".{module}", __package__)
    fn = getattr(mod, func, None)
    if fn is None:
        raise FactoryError("config.invalid", f"{module}.py defines no {func} for check {name!r}",
                           hint=f"add {func}(spec, ctx) to {module}.py")
    return fn
