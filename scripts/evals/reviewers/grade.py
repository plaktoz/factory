from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from cases import Case

LINE_SLACK = 3


@dataclass
class Grade:
    case: str
    planted: bool
    artifact: bool
    where: str | None
    schema_ok: bool | None
    gate_passed: bool | None
    gate_code: str | None
    findings: int
    blocking: int
    cited: bool
    cited_blocking: bool


def grade(case: Case, artifact: Path | None, where: str | None, schema_ok: bool | None, gate_passed: bool | None,
          gate_code: str | None) -> Grade:
    findings: list[dict] = []
    if artifact is not None and artifact.is_file():
        try:
            doc = json.loads(artifact.read_text())
            findings = [f for f in doc.get("findings", []) if isinstance(f, dict)]
        except ValueError:
            findings = []
    blocking = [f for f in findings if f.get("severity") in ("medium", "high")]
    line = case.planted_line()

    def hits(rows: list[dict]) -> bool:
        if case.planted is None or line is None:
            return False
        return any(f.get("file") == case.planted[0] and isinstance(f.get("line"), int)
                   and abs(f["line"] - line) <= LINE_SLACK for f in rows)

    return Grade(case.id, case.planted is not None, artifact is not None and artifact.is_file(), where, schema_ok,
                 gate_passed, gate_code,
                 len(findings), len(blocking), hits(findings), hits(blocking))


def summarize(grades: list[Grade]) -> dict:
    planted = [g for g in grades if g.planted]
    clean = [g for g in grades if not g.planted]
    return {
        "runs": len(grades),
        "planted_runs": len(planted),
        "clean_runs": len(clean),
        "artifact_at_engine_path": sum(g.where == "task_dir" for g in grades),
        "artifact_at_guessed_path": sum(g.where == "guessed_path" for g in grades),
        "no_artifact_anywhere": sum(not g.artifact for g in grades),
        "schema_valid": sum(g.schema_ok is True for g in grades),
        "gate_passed_wiring": sum(g.gate_passed is True for g in grades),
        "recall_cited": sum(g.cited for g in planted),
        "recall_cited_blocking": sum(g.cited_blocking for g in planted),
        "false_alarm_runs_blocking": sum(g.blocking > 0 for g in clean),
        "clean_runs_with_any_finding": sum(g.findings > 0 for g in clean),
        "planted_runs_with_no_findings": sum(g.findings == 0 for g in planted),
        "planted_blocked_for_the_right_reason": sum(g.gate_code == "gate.blocking_findings" for g in planted),
    }


def as_dicts(grades: list[Grade]) -> list[dict]:
    return [asdict(g) for g in grades]
