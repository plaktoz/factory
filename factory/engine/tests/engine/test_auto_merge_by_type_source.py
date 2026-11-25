"""Section 20, integration test 2: a small chore end to end. With an explicit type it auto-merges; the same chore typed
by the triage model goes to human review.

Both runs go through the engine, from triage to the pull request and then to green CI, with the policy file the kit
snapshot holds (`.factory/config/merge-policy.yaml`) and the fake pull request service. Nothing patches the merge rules.
"""

import json

from engine_helpers import TRIAGE_JSON, chore_script

from factory_engine import gitops, state
from factory_engine.kit import STARTER_MERGE_POLICY

RUN = "bump-q1w2e"
CHORE_POLICY = STARTER_MERGE_POLICY.replace("workflows: []", "workflows: [chore]")  # the owner turns auto-merge on for chores


def _kit_policy(run_dir, text: str) -> None:
    kit = state.factory_home() / "kits" / state.read_run(run_dir).kit_hash / ".factory" / "config"
    kit.mkdir(parents=True, exist_ok=True)
    (kit / "merge-policy.yaml").write_text(text)


def _parked_chore(new_run, engine, type_source: str):
    run_dir = new_run()
    _kit_policy(run_dir, CHORE_POLICY)
    script, writes = chore_script(run_dir)
    writes["rules"] = {"triage.json": json.dumps({**json.loads(TRIAGE_JSON), "type_source": type_source})}
    eng, worker = engine(script, writes)
    real_start = worker.start

    def start(ctx, conf, log):
        if ctx.task_id == "change":  # the one-line change the chore makes, so the join commits a real diff
            (ctx.worktree / "services" / "api.py").write_text("x = 2\n")
        return real_start(ctx, conf, log)

    worker.start = start
    assert eng.run([RUN]).runs == {RUN: "awaiting_approval"}
    run = state.read_run(run_dir)
    assert run.pr is not None and run.request.type_source == type_source
    assert gitops.changed_files(run.worktree, "origin/main") == ["services/api.py"]  # a real one-line diff is on the branch
    return eng, run_dir, run.pr


def test_a_chore_with_an_explicit_type_is_merged_by_github_when_ci_turns_green(new_run, engine, prs):
    eng, run_dir, pr = _parked_chore(new_run, engine, "explicit")
    prs.set_ci(pr, "green")
    eng.tick(RUN)
    assert prs.prs[pr.number].merged_with == "squash" and prs.prs[pr.number].auto_merge is True
    assert prs.prs[pr.number].state == "merged"
    assert prs.prs[pr.number].comments == ["Merge check with CI green: Auto-merge: every rule passed"]
    assert eng.run([RUN]).runs == {RUN: "done"}  # the next pass sees the merge and ends the run
    assert state.read_run(run_dir).status == "done"


def test_the_same_chore_typed_by_the_triage_model_is_left_for_a_person(new_run, engine, prs):
    eng, run_dir, pr = _parked_chore(new_run, engine, "llm")
    prs.set_ci(pr, "green")
    eng.tick(RUN)
    assert prs.prs[pr.number].merged_with is None and prs.prs[pr.number].auto_merge is False
    assert prs.prs[pr.number].state == "open"
    (comment,) = prs.prs[pr.number].comments
    assert comment.startswith("Merge check with CI green: Human review:")
    verdict = json.loads((run_dir / "merge.json").read_text())
    assert verdict["auto"] is False
    assert next(r for r in verdict["rules"] if r["rule"] == "auto.type_source")["passed"] is False
    assert eng.run([RUN]).runs == {RUN: "awaiting_approval"}  # it waits for a human merge
    prs.human_merge(pr)
    assert eng.run([RUN]).runs == {RUN: "done"}
