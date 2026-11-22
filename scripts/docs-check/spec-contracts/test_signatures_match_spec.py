"""W0.6: the public functions in factory_engine match the signatures the spec declares.

For every signature in a spec code block whose module file exists, the function (or method) must exist and have
the same parameter names, in the same order, with the same kind (positional or keyword-only) and the same
default-or-not. Return annotations and parameter annotations are compared as text, ignoring spacing and
`from __future__ import annotations`. A signature whose module file does not exist yet is `pending`: it is
counted, and the count may only go down (PENDING_AT_WAVE_0 below), so a later wave cannot leave one out.
"""

import ast
import importlib
import inspect
import re
from pathlib import Path

import pytest

from spec_blocks import REPO
from spec_signatures import Param, Sig, spec_signatures

ENGINE = REPO / "factory" / "engine" / "factory_engine"
SIGS = spec_signatures()

def module_for(file: str) -> str:
    return "factory_engine." + file[:-3].replace("/", ".")


def exists(sig: Sig) -> bool:
    """Built means the function (or method) can be found. A module file can exist before its module is built:
    config.py holds only the Config type until wave 1 builds module 3."""
    if not (ENGINE / sig.file).is_file():
        return False
    try:
        resolve(sig)
    except (ImportError, AttributeError):
        return False
    return True


def norm(text: str | None) -> str | None:
    if text is None:
        return None
    try:
        return ast.unparse(ast.parse(text, mode="eval"))
    except SyntaxError:
        return re.sub(r"\s+", "", text)


def code_params(fn) -> tuple[Param, ...]:
    out = []
    for p in inspect.signature(fn).parameters.values():
        if p.name in ("self", "cls"):
            continue
        kind = {p.POSITIONAL_ONLY: "positional", p.POSITIONAL_OR_KEYWORD: "positional", p.KEYWORD_ONLY: "keyword_only",
                p.VAR_POSITIONAL: "var_positional", p.VAR_KEYWORD: "var_keyword"}[p.kind]
        ann = None if p.annotation is inspect.Parameter.empty else p.annotation
        out.append(Param(p.name, kind, p.default is not inspect.Parameter.empty, ann if isinstance(ann, str) else None))
    return tuple(out)


def resolve(sig: Sig):
    mod = importlib.import_module(module_for(sig.file))
    if "." in sig.key:
        cls, meth = sig.key.split(".", 1)
        return getattr(getattr(mod, cls), meth)
    return getattr(mod, sig.key)


def returns_text(fn) -> str | None:
    r = inspect.signature(fn).return_annotation
    return None if r is inspect.Signature.empty else (r if isinstance(r, str) else getattr(r, "__name__", str(r)))


BUILT = [s for s in SIGS if exists(s)]
PENDING = [s for s in SIGS if not exists(s)]


def test_the_parser_reads_the_whole_spec():
    # 146 at wave 0; 147 since module 4 added triage_candidates (2026-11-15, built with its tests).
    # 151 since 2026-11-21: module 7 lists PullRequests.comment, and module 13 lists changed_since_base, reviewers_for and
    # green_check_done (owner decision D1, ADR 2026-11-21-auto-merge-is-checked-at-open-and-at-green).
    # 152 since 2026-11-22: module 16 lists api.doctor, which composes module 3's doctor with 10 and 17A.
    # 153 since 2026-11-22: module 17A lists format_changed_files (D8), and language_tasks takes the changed paths (D5).
    assert len(SIGS) == 153, f"{len(SIGS)} signatures parsed, expected 153: the parser regressed, or a spec signature was removed or added"
    assert all(s.file for s in SIGS), "a signature has no module file; add a `# file.py` comment to its block"


@pytest.mark.parametrize("sig", BUILT, ids=lambda s: f"{s.file}:{s.key}")
def test_built_signature_matches_spec(sig):
    try:
        fn = resolve(sig)
    except (ImportError, AttributeError) as e:
        pytest.fail(f"{sig.file} exists but {sig.key} cannot be resolved: {e}")
    have, want = code_params(fn), sig.params
    assert [(p.name, p.kind, p.has_default) for p in have] == [(p.name, p.kind, p.has_default) for p in want], \
        f"{sig.key}: code {[p.name for p in have]} != spec {[p.name for p in want]}"
    for h, w in zip(have, want):
        if w.annotation is not None and h.annotation is not None:
            assert norm(h.annotation) == norm(w.annotation), f"{sig.key}({w.name}): {h.annotation} != {w.annotation}"
    if sig.returns is not None:
        got = returns_text(fn)
        assert got is None or norm(got) == norm(sig.returns), f"{sig.key} returns {got}, spec says {sig.returns}"


# Measured at the end of wave 0 (2026-11-14): 146 signatures in the spec, 14 built (the protocol methods of
# TrackerAdapter, PullRequests, WorkerAdapter and Clock), 132 pending for waves 1 to 4. The number may only go
# down. A wave that deletes a spec signature instead of building it leaves the parser-size test above unchanged,
# so a removed signature is caught by the count of the spec, which the parser-size test pins at 146.
PENDING_AT_WAVE_0 = 132


def test_pending_count_never_grows():
    assert len(PENDING) <= PENDING_AT_WAVE_0


def test_report_what_is_pending():
    """Prints the pending count per file in the -s output; never fails. The number above is the gate."""
    by_file: dict[str, int] = {}
    for s in PENDING:
        by_file[s.file] = by_file.get(s.file, 0) + 1
    print(f"\nbuilt: {len(BUILT)}  pending: {len(PENDING)}  files: {len(by_file)}  per file: {by_file}")


# The fakes implement the protocols above. Each protocol method in the spec must exist on its fake with the same
# parameter names, kinds and defaults, so a fake that drifts from the contract fails here and not in a later wave.
FAKES = {
    "Clock": [("factory_engine.clock", "FakeClock"), ("factory_engine.clock", "SystemClock")],
    "TrackerAdapter": [("factory_engine.adapters.tracker.fake", "FakeTracker")],
    "PullRequests": [("factory_engine.fake_prs", "FakePullRequests")],
    "WorkerAdapter": [("factory_engine.adapters.worker.fake", "FakeWorkerAdapter")],
}
FAKE_CASES = [(proto, mod, cls, s) for proto, impls in FAKES.items() for mod, cls in impls
              for s in BUILT if s.key.startswith(proto + ".")]


def test_every_protocol_has_a_fake_checked_below():
    assert FAKE_CASES and {c[0] for c in FAKE_CASES} == set(FAKES)


@pytest.mark.parametrize("proto,mod,cls,sig", FAKE_CASES, ids=lambda x: x if isinstance(x, str) else getattr(x, "key", ""))
def test_fake_matches_the_protocol_signature(proto, mod, cls, sig):
    meth = sig.key.split(".", 1)[1]
    fn = getattr(getattr(importlib.import_module(mod), cls), meth)
    have = [(p.name, p.kind, p.has_default) for p in code_params(fn)]
    want = [(p.name, p.kind, p.has_default) for p in sig.params]
    assert have == want, f"{cls}.{meth}: {[h[0] for h in have]} != spec {[w[0] for w in want]}"
