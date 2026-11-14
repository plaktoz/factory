"""Triage (module 4): choose a request's type and workflow by rules, and gate on the result.

The rules never return `llm`. When they cannot decide, the result has no type, and the `classify` task (an LLM
skill, module 8's gate) fills triage.json with `type_source: llm`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import Config
from .types import GateContext, GateResult, GateSpec, Request

# Built-in request types and the workflow each one selects (module 5 ships these workflows).
TYPE_WORKFLOW: dict[str, str] = {
    "bug": "bug-fix",
    "feature": "feature",
    "new-app": "new-app",
    "chore": "chore",
    "research": "research",
}

KEYWORDS: dict[str, tuple[str, ...]] = {
    "bug": ("bug", "fix", "fails", "failing", "crash", "broken", "regression", "error", "exception"),
    "chore": ("chore", "bump", "upgrade", "cleanup", "dependency", "rename"),
    "feature": ("feature", "add", "support", "implement", "enable"),
    "research": ("research", "investigate", "compare", "evaluate", "spike"),
    "new-app": ("scaffold", "bootstrap", "from scratch", "new app"),
}

RULE_CONFIDENCE = 1.0
KEYWORD_CONFIDENCE = 0.9  # one type matched and no other; anything less decisive falls to the LLM


@dataclass
class TriageResult:
    """The fields of triage.schema.json (schema_version is added when the file is written)."""

    type: str | None
    workflow: str | None
    confidence: float
    type_source: str  # explicit | label | front_matter | keyword | llm


def _result(type_: str, confidence: float, source: str) -> TriageResult:
    return TriageResult(type_, TYPE_WORKFLOW[type_], confidence, source)


def triage_rules(request: Request, cfg: Config) -> TriageResult:
    """Order: explicit type, then a type label, then front matter, then keywords. The first rule that decides wins."""
    if request.type and request.type_source == "explicit":
        return _result(request.type, RULE_CONFIDENCE, "explicit")
    labelled = sorted({lab.strip().lower() for lab in request.source.labels} & set(TYPE_WORKFLOW))
    if len(labelled) == 1:
        return _result(labelled[0], RULE_CONFIDENCE, "label")
    if request.type and request.type_source == "front_matter":
        return _result(request.type, RULE_CONFIDENCE, "front_matter")
    return _keywords(request)


def _keywords(request: Request) -> TriageResult:
    text = f"{request.title}\n{request.source.body}".lower()
    matched = [t for t, words in KEYWORDS.items()
               if any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)]
    if len(matched) == 1:
        return _result(matched[0], KEYWORD_CONFIDENCE, "keyword")
    # Nothing matched, or several types matched: no decision. The classify task decides.
    return TriageResult(None, None, 0.0, "keyword")


def check_type_resolved(spec: GateSpec, ctx: GateContext) -> GateResult:
    """Passes when triage.json names a type and a workflow (used by the `_triage` stage, module 8)."""
    doc: dict | None = None
    if ctx.artifact is not None and ctx.artifact.is_file():
        try:
            doc = json.loads(ctx.artifact.read_text())
        except (OSError, json.JSONDecodeError):
            doc = None
    ok = bool(doc and doc.get("type") and doc.get("workflow"))
    return GateResult(passed=ok, gate="type-resolved", code="ok" if ok else "gate.type_unresolved",
                      output_tail="" if ok else "triage.json has no type or workflow",
                      details={"type": (doc or {}).get("type"), "workflow": (doc or {}).get("workflow")})
