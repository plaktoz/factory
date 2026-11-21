"""Module 9 acceptance criteria for the prompt and the helpers-ledger gate, plus the FakeWorkerAdapter cases."""

import json

import pytest

from factory_engine.adapters.worker.base import HarnessConfig
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, failed, ok, timeout
from factory_engine.prompt import build_prompt, check_helpers_ledger, helper_policy_words, LEDGER
from factory_engine.types import GateContext, GateSpec, HelperPolicy

from workers_helpers import ctx_for, request


# ---- the prompt -------------------------------------------------------------------------------------------------

def test_the_prompt_is_the_same_for_the_same_context(worktree, task_dir):
    ctx = ctx_for(worktree, task_dir)
    assert build_prompt(ctx) == build_prompt(ctx)


def test_the_helper_policy_is_stated_in_plain_words_for_each_mode():
    off = helper_policy_words(HelperPolicy("off", 0, [], None))
    assert "Helpers are off" in off and f"{LEDGER}" in off
    auto = helper_policy_words(HelperPolicy("auto", 2, ["api-code", "tests"], 15))
    assert "at most 2 helpers" in auto and "api-code, tests" in auto and "15 minutes" in auto
    one = helper_policy_words(HelperPolicy("native", 1, [], None))
    assert "at most 1 helper " in one


def test_the_prompt_names_the_artifact_file_and_the_schema(worktree, task_dir):
    text = build_prompt(ctx_for(worktree, task_dir, artifact_name="triage.json"))
    assert str(task_dir / "triage.json") in text
    assert "stage-report" in text


def test_the_prompt_gives_the_real_task_folder_path_not_only_the_variable(worktree, task_dir):
    """A worker with no Bash cannot expand $FACTORY_TASK_DIR, so the prompt must carry the path itself.

    In a real run (2026-11-21) the worker wrote the correct change three times and never wrote its artifact, because
    it was told to write to the literal text `$FACTORY_TASK_DIR/change.json` and had no way to read the variable."""
    text = build_prompt(ctx_for(worktree, task_dir, artifact_name="change.json"))
    output = text.split("## Output", 1)[1]
    assert str(task_dir / "change.json") in output
    assert str(task_dir / "progress.md") in output
    assert str(task_dir / "helpers.jsonl") in output


def test_a_prompt_without_a_skill_still_gives_the_request_and_scope(worktree, task_dir):
    ctx = ctx_for(worktree, task_dir, skill=None)
    text = build_prompt(ctx)
    assert "Fix the total" in text and "src/**" in text
    assert "factory-" not in text.split("## Scope")[0].split("## Request")[0]


def test_a_task_built_from_a_question_list_shows_its_question_in_the_prompt(worktree, task_dir):
    ctx = ctx_for(worktree, task_dir)
    ctx.question = "Which regions is it available in?"
    text = build_prompt(ctx)
    assert "## Your question" in text and "Which regions is it available in?" in text


def test_a_task_with_no_question_has_no_question_section(worktree, task_dir):
    assert "Your question" not in build_prompt(ctx_for(worktree, task_dir))


# ---- the helpers-ledger gate ---------------------------------------------------------------------------------

def git(cwd, *args):
    import subprocess
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@x.invalid", "-C", str(cwd), *args],
                   check=True, capture_output=True)


@pytest.fixture
def repo_with_change(tmp_path):
    """A worktree whose base commit is HEAD~1 and whose HEAD changes one file."""
    import subprocess
    wt = tmp_path / "gate-wt"
    subprocess.run(["git", "init", "-q", "-b", "main", str(wt)], check=True)
    git(wt, "commit", "-q", "--allow-empty", "-m", "base")
    (wt / "a.py").write_text("x = 1\n")
    git(wt, "add", "a.py")
    git(wt, "commit", "-q", "-m", "change")
    return wt


def gate_ctx(worktree, task_dir, base="HEAD~1"):
    from factory_engine.config import Config
    return GateContext(run=None, stage="fix", task_id="backend", worktree=worktree, task_dir=task_dir, artifact=None,
                       task_base=base, scope=["*"], deny=[], cfg=Config({}, None))


def write_ledger(task_dir, entries):
    (task_dir).mkdir(parents=True, exist_ok=True)
    (task_dir / LEDGER).write_text("".join(json.dumps(e) + "\n" for e in entries))


def test_the_gate_fails_when_files_changed_and_the_ledger_is_missing(repo_with_change, task_dir):
    spec = GateSpec("check", None, "helpers-ledger", None, {"mode": "auto", "max": 2})
    r = check_helpers_ledger(spec, gate_ctx(repo_with_change, task_dir))
    assert r.passed is False and r.code == "gate.ledger_missing"


def test_the_gate_passes_with_a_ledger_inside_the_maximum(repo_with_change, task_dir):
    write_ledger(task_dir, [{"name": "api", "purpose": "code", "started": "t"}])
    spec = GateSpec("check", None, "helpers-ledger", None, {"mode": "auto", "max": 2})
    r = check_helpers_ledger(spec, gate_ctx(repo_with_change, task_dir))
    assert r.passed is True and r.details["helpers"] == 1


def test_the_gate_fails_when_the_ledger_exceeds_the_maximum(repo_with_change, task_dir):
    write_ledger(task_dir, [{"name": n, "purpose": "x", "started": "t"} for n in ("a", "b", "c")])
    spec = GateSpec("check", None, "helpers-ledger", None, {"mode": "auto", "max": 2})
    r = check_helpers_ledger(spec, gate_ctx(repo_with_change, task_dir))
    assert r.passed is False and r.code == "gate.ledger_over_max"


def test_helpers_off_with_no_files_changed_and_no_ledger_passes(tmp_path, task_dir):
    import subprocess
    wt = tmp_path / "quiet"
    subprocess.run(["git", "init", "-q", "-b", "main", str(wt)], check=True)
    git(wt, "commit", "-q", "--allow-empty", "-m", "base")
    spec = GateSpec("check", None, "helpers-ledger", None, {"mode": "off", "max": 0})
    r = check_helpers_ledger(spec, gate_ctx(wt, task_dir, base="HEAD"))
    assert r.passed is True


def test_the_same_request_gives_gate_evidence_of_the_same_shape_with_helpers_off_and_on(repo_with_change, task_dir, tmp_path):
    off_dir = tmp_path / "off-work"
    on_dir = tmp_path / "on-work"
    write_ledger(off_dir, [])
    write_ledger(on_dir, [{"name": "api", "purpose": "code", "started": "t"}])
    off = check_helpers_ledger(GateSpec("check", None, "helpers-ledger", None, {"mode": "off", "max": 0}),
                               gate_ctx(repo_with_change, off_dir))
    on = check_helpers_ledger(GateSpec("check", None, "helpers-ledger", None, {"mode": "auto", "max": 2}),
                              gate_ctx(repo_with_change, on_dir))
    assert set(vars(off)) == set(vars(on))
    assert set(off.details) == set(on.details)


# ---- FakeWorkerAdapter, the cases module 9 lists -------------------------------------------------------------

def test_the_fake_scripts_success_failure_and_timeout_per_task(tmp_path, worktree, task_dir):
    fake = FakeWorkerAdapter({"backend": [ok(), failed("rate_limit"), timeout()],
                              "tests": [failed("crash")]})
    conf = HarnessConfig("fake", None, [], {})
    got = []
    for n in (1, 2, 3):
        h = fake.start(ctx_for(worktree, task_dir, attempt=n), conf, tmp_path / f"log{n}")
        got.append(fake.wait(h, 60).exit)
    assert got == ["ok", "failed", "timeout"]
    h = fake.start(ctx_for(worktree, task_dir, task_id="tests"), conf, tmp_path / "logt")
    assert fake.wait(h, 60).error_kind == "crash"


def test_the_fake_writes_each_tasks_artifact_into_its_task_folder(tmp_path, worktree, task_dir):
    fake = FakeWorkerAdapter({"backend": [ok()]}, writes={"backend": {"stage.json": '{"x": 1}'}})
    fake.start(ctx_for(worktree, task_dir), HarnessConfig("fake", None, [], {}), tmp_path / "log")
    assert json.loads((task_dir / "stage.json").read_text()) == {"x": 1}


def test_the_fake_refuses_an_attempt_nobody_scripted(tmp_path, worktree, task_dir):
    fake = FakeWorkerAdapter({"backend": [ok()]})
    conf = HarnessConfig("fake", None, [], {})
    fake.start(ctx_for(worktree, task_dir), conf, tmp_path / "log")
    with pytest.raises(AssertionError):
        fake.start(ctx_for(worktree, task_dir, attempt=2), conf, tmp_path / "log2")
