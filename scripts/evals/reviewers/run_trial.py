"""Reviewer trial runner (P2-9). Usage: uv run --project factory/engine python scripts/evals/reviewers/run_trial.py [--runs N] [--arm engine|told] [--only ID,ID] [--dry]"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
KIT = ROOT / "factory"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(KIT / "engine"))

from cases import BASE, CASES, Case  # noqa: E402
from factory_engine.types import GateSpec, Stage, TaskSpec  # noqa: E402
from grade import as_dicts, grade, summarize  # noqa: E402

RESULTS = HERE / "results"
WORKFLOW = "reviewer-eval"


def gate_label(spec: GateSpec) -> str:
    return spec.check or spec.schema or " ".join(spec.cmd or [])


def build_worktree(case: Case, wt: Path) -> None:
    for path, text in BASE.items():
        (wt / path).parent.mkdir(parents=True, exist_ok=True)
        (wt / path).write_text(text)
    git = ["git", "-c", "user.name=trial", "-c", "user.email=trial@example.invalid"]
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], cwd=wt, check=True)
    for path, text in case.files().items():
        (wt / path).parent.mkdir(parents=True, exist_ok=True)
        (wt / path).write_text(text)


def run_one(case: Case, run_no: int, out: Path, dry: bool, arm: str, stage: Stage, task: TaskSpec) -> dict:
    from factory_engine.adapters.worker.base import HarnessConfig, TaskContext
    from factory_engine.adapters.worker.claude import ClaudeAdapter
    from factory_engine.config import Config
    from factory_engine.errors import FactoryError
    from factory_engine.gates import run_gates
    from factory_engine.shims import generate_shims
    from factory_engine.skills import resolve_skill, use_kit
    from factory_engine.validate import validate
    from factory_engine.types import GateContext, HelperPolicy, Request, Source

    use_kit(KIT)
    work = Path(tempfile.mkdtemp(prefix=f"trial-{case.id}-"))
    wt, task_dir = work / "wt", work / "task" / "work"
    wt.mkdir()
    task_dir.mkdir(parents=True)
    build_worktree(case, wt)
    skill = resolve_skill(task.skill, wt, Config(machine={}, repo={}))
    generate_shims(wt, ["claude"], [skill])
    out_name = task.out

    src = Source("cli", f"ledger#{case.id}", case.title, case.title, [], None, [])
    request = Request(case.id, src, "sha", "ledger", case.title, "chore", "label", None,
                      ["the change follows every standard in AGENTS.md"])
    notes = ["Files changed by this task, relative to the worktree root: " + ", ".join(case.changed)]
    if arm == "told":
        notes += [f"Write the artifact to this absolute path: {task_dir}/{out_name}",
                  'Its top level is {"schema_version": 1, "findings": [...]}. Each finding has exactly these keys: '
                  '"file", "line" (integer), "severity" (low, medium or high), "rule" and "message".']
    ctx = TaskContext(run_id="trial", task_id=case.id, stage=stage.id, attempt=run_no, skill=skill,
                      request=request, worktree=wt, task_dir=task_dir, scope=[], deny=[],
                      helpers=HelperPolicy("off", 0, [], None), feedback=[], notes=notes, progress=None,
                      output_schema="review-findings", model=task.model, mcp=[], practices=[],
                      artifact_name=out_name)
    row: dict = {"case": case.id, "run": run_no, "arm": arm, "work": str(work)}
    if dry:
        return {**row, "dry": True, "prompt_ok": True, "skill": task.skill, "out": out_name,
                "model": task.model, "timeout_minutes": task.timeout_minutes,
                "gate": [gate_label(g) for g in stage.gate]}

    adapter = ClaudeAdapter()
    conf = HarnessConfig(command="claude", model=task.model, args=[], env={})
    log = task_dir.parent / "worker.log"
    started = time.time()
    handle = adapter.start(ctx, conf, log)
    result = adapter.wait(handle, task.timeout_minutes * 60)
    row.update(exit=result.exit, error_kind=result.error_kind, input_tokens=result.input_tokens,
               output_tokens=result.output_tokens, models=result.models_observed,
               seconds=round(time.time() - started, 1))

    art, where = result.artifact, ("task_dir" if result.artifact else None)
    if art is None and (task_dir.parent / out_name).is_file():
        art, where = task_dir.parent / out_name, "guessed_path"
    schema_ok = gate_passed = None
    gate_code = "gate.no_artifact"
    if art is not None:
        (out / f"{arm}-{case.id}.run{run_no}.json").write_text(art.read_text())
        try:
            validate(json.loads(art.read_text()), "review-findings")
            schema_ok = True
        except (ValueError, FactoryError):
            schema_ok = False
    if where == "task_dir":
        gctx = GateContext(run=None, stage=stage.id, task_id=case.id, worktree=wt, task_dir=task_dir,  # type: ignore[arg-type]
                           artifact=art, task_base=None, scope=[], deny=[], cfg=Config(machine={}, repo={}))
        g = run_gates(stage.gate, gctx)[-1]
        gate_passed, gate_code = g.passed, g.code
    row["grade"] = as_dicts([grade(case, art, where, schema_ok, gate_passed, gate_code)])[0]
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--arm", choices=["engine", "told"], default="engine",
                    help="engine: the prompt as the engine builds it; told: plus the absolute artifact path and field names")
    ap.add_argument("--dry", action="store_true", help="build every worktree and prompt, start no worker")
    a = ap.parse_args()
    only = set(filter(None, a.only.split(",")))
    cases = [c for c in CASES if not only or c.id in only]

    from factory_engine.config import Config
    from factory_engine.skills import use_kit
    from factory_engine.workflow import load_workflow

    os.environ["FACTORY_HOME"] = tempfile.mkdtemp(prefix="trial-home-")
    use_kit(KIT)
    wf = load_workflow(ROOT, Config(machine={}, repo={}), WORKFLOW)
    stage = next(s for s in wf.stages if s.id == "review")
    task = next(t for t in stage.tasks if t.id == "standards")
    out = RESULTS / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    jobs = [(c, n) for c in cases for n in range(1, a.runs + 1)]
    with ThreadPoolExecutor(a.jobs) as pool:
        rows = list(pool.map(lambda j: run_one(j[0], j[1], out, a.dry, a.arm, stage, task), jobs))
    (out / "rows.json").write_text(json.dumps(rows, indent=1))
    if a.dry:
        print(f"dry: {len(rows)} worktrees built, no worker started")
        return 0

    from grade import Grade
    grades = [Grade(**r["grade"]) for r in rows if "grade" in r]
    summary = summarize(grades)
    summary["tokens_in"] = sum(r.get("input_tokens") or 0 for r in rows)
    summary["tokens_out"] = sum(r.get("output_tokens") or 0 for r in rows)
    summary["models"] = sorted({m for r in rows for m in r.get("models", [])})
    summary["failed_attempts"] = [(r["case"], r.get("exit"), r.get("error_kind")) for r in rows if r.get("exit") != "ok"]
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    print("results:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
