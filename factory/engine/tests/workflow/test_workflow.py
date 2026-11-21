"""Module 5 acceptance criteria for phase 1a: the loader, the validator, tasks_from and helper expansion.

Plugins, hooks and deterministic plugin tasks are phase 1b and have no tests here.
"""

import json
import subprocess
from pathlib import Path

import pytest

from factory_engine import skills
from factory_engine.config import Config
from factory_engine.errors import FactoryError
from factory_engine.types import HelperPolicy, Problem, Stage, TaskSpec
from factory_engine.workflow import expand_helpers, expand_tasks_from, load_workflow, validate_workflow

KIT = Path(__file__).resolve().parents[3]  # factory/
CFG = Config(machine={}, repo={})

BUILT_IN_1A = ["_triage", "bug-fix", "chore"]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    skills.use_kit(KIT)
    yield
    skills.use_kit(Path(skills.__file__).resolve().parents[2])


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / ".factory" / "config" / "workflows").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    return r


def write(repo: Path, name: str, text: str) -> None:
    (repo / ".factory" / "config" / "workflows" / f"{name}.yaml").write_text(text)


def load_text(repo: Path, text: str, name: str = "t") -> object:
    write(repo, name, text)
    return load_workflow(repo, CFG, name)


def fails(repo: Path, text: str, name: str = "t") -> FactoryError:
    write(repo, name, text)
    with pytest.raises(FactoryError) as e:
        load_workflow(repo, CFG, name)
    assert e.value.code == "config.invalid"
    assert e.value.kind == "fail_fast"
    return e.value


def wf_text(stages: str, header: str = "") -> str:
    return f"name: t\ntype: t\nsink: pull_request\n{header}stages:\n{stages}"


def _line_of(text: str, needle: str) -> int:
    return next(i for i, line in enumerate(text.splitlines(), 1) if needle in line)


# ---- criterion 1: built-in workflows load ----

@pytest.mark.parametrize("name", BUILT_IN_1A)
def test_built_in_workflow_loads_without_problems(repo, name):
    wf = load_workflow(repo, CFG, name)
    assert wf.name == name
    assert wf.stages
    assert validate_workflow(wf, CFG) == []


def test_bug_fix_matches_the_spec_shape(repo):
    wf = load_workflow(repo, CFG, "bug-fix")
    assert wf.type == "bug" and wf.sink == "pull_request" and wf.policy.write is True
    assert [s.id for s in wf.stages] == ["reproduce", "root-cause", "propose", "fix", "verify", "review"]
    fix = next(s for s in wf.stages if s.id == "fix")
    assert [t.id for t in fix.tasks] == ["backend", "frontend"]
    assert fix.tasks[1].needs == ["backend"]
    assert fix.on_fail.goto == "root-cause" and fix.on_fail.max == 2
    assert fix.tasks[0].helpers.split_hints == ["api-code", "tests"]
    propose = next(s for s in wf.stages if s.id == "propose")
    assert propose.approval == "human" and propose.on_reject == "root-cause"
    assert all(s.source == "workflow" for s in wf.stages)


def test_chore_is_a_write_workflow_with_a_pull_request_sink(repo):
    wf = load_workflow(repo, CFG, "chore")
    assert wf.type == "chore" and wf.sink == "pull_request" and wf.policy.write is True


def test_triage_matches_the_spec_shape(repo):
    wf = load_workflow(repo, CFG, "_triage")
    (stage,) = wf.stages
    assert [t.id for t in stage.tasks] == ["rules", "classify"]
    assert stage.tasks[0].cmd == ["factory", "triage"] and stage.tasks[0].skill is None
    assert stage.tasks[1].needs == ["rules"] and stage.tasks[1].when["confidence_below"] == 0.8
    assert stage.approval == "when-low-confidence"
    assert stage.gate[0].check == "type-resolved"


def test_a_deterministic_task_gets_no_retries_and_a_worker_task_gets_the_default(repo):
    wf = load_workflow(repo, CFG, "bug-fix")
    verify = next(s for s in wf.stages if s.id == "verify")
    fix = next(s for s in wf.stages if s.id == "fix")
    assert all(t.retries == 0 for t in verify.tasks)
    assert all(t.retries == wf.defaults.retries == 2 for t in fix.tasks)


def test_verify_syncs_the_base_by_default(repo):
    wf = load_workflow(repo, CFG, "bug-fix")
    assert {s.id for s in wf.stages if s.sync_base} == {"verify"}


def test_a_repo_workflow_beats_the_kit_workflow(repo):
    write(repo, "chore", wf_text("  - id: only\n    tasks: [{id: a, cmd: [make, test]}]\n").replace("name: t\ntype: t", "name: chore\ntype: chore"))
    wf = load_workflow(repo, CFG, "chore")
    assert [s.id for s in wf.stages] == ["only"]


def test_an_unknown_workflow_name_fails_fast(repo):
    with pytest.raises(FactoryError) as e:
        load_workflow(repo, CFG, "nope")
    assert e.value.code == "config.invalid" and "nope" in e.value.message


@pytest.mark.parametrize("name", ["../x", "Bug", "a/b", ""])
def test_a_workflow_name_that_is_not_a_plain_name_is_refused(repo, name):
    with pytest.raises(FactoryError) as e:
        load_workflow(repo, CFG, name)
    assert e.value.code == "config.invalid"


def test_defaults_apply_when_the_file_omits_them(repo):
    wf = load_text(repo, wf_text("  - id: a\n    tasks: [{id: x, cmd: [make, test]}]\n"))
    assert (wf.defaults.retries, wf.defaults.timeout_minutes, wf.defaults.checkpoint_every_minutes,
            wf.defaults.max_restarts) == (2, 30, 10, 3)
    assert wf.policy.write is False
    assert wf.stages[0].tasks[0].timeout_minutes == 30


def test_a_file_that_omits_sink_gets_comment_when_read_only_and_pull_request_when_writing(repo):
    ro = load_text(repo, "stages:\n  - id: a\n    tasks: [{id: x, cmd: [make, test]}]\n")
    rw = load_text(repo, "policy: {write: true}\nstages:\n  - id: a\n    tasks: [{id: x, cmd: [make, test]}]\n", name="rw")
    assert ro.sink == "comment" and rw.sink == "pull_request"


# ---- criterion 2: cycle, unknown skill, unknown check, unknown goto are each reported with their path ----

def test_a_needs_cycle_between_stages_is_reported_with_its_path(repo):
    e = fails(repo, wf_text(
        "  - {id: a, needs: [b], tasks: [{id: x, cmd: [make, test]}]}\n"
        "  - {id: b, needs: [c], tasks: [{id: y, cmd: [make, test]}]}\n"
        "  - {id: c, needs: [a], tasks: [{id: z, cmd: [make, test]}]}\n"))
    assert "needs cycle: a -> b -> c -> a" in e.message


def test_a_needs_cycle_between_tasks_is_reported_with_its_stage(repo):
    e = fails(repo, wf_text(
        "  - id: a\n    tasks:\n      - {id: x, cmd: [make, test], needs: [y]}\n      - {id: y, cmd: [make, test], needs: [x]}\n"))
    assert "stages.a: tasks needs cycle: x -> y -> x" in e.message


def test_a_stage_that_needs_itself_is_a_cycle(repo):
    e = fails(repo, wf_text("  - {id: a, needs: [a], tasks: [{id: x, cmd: [make, test]}]}\n"))
    assert "needs cycle: a -> a" in e.message


def test_a_needs_on_an_unknown_stage_is_reported_with_its_path(repo):
    e = fails(repo, wf_text("  - {id: a, needs: [ghost], tasks: [{id: x, cmd: [make, test]}]}\n"))
    assert "stages.a.needs: unknown stage 'ghost'" in e.message


def test_a_needs_on_an_unknown_task_is_reported_with_its_path(repo):
    e = fails(repo, wf_text("  - id: a\n    tasks: [{id: x, cmd: [make, test], needs: [ghost]}]\n"))
    assert "stages.a.tasks.x.needs: unknown task 'ghost'" in e.message


def test_an_unknown_skill_is_reported_with_its_path(repo):
    e = fails(repo, wf_text("  - id: a\n    tasks: [{id: x, skill: no-such-skill}]\n"))
    assert "stages.a.tasks.x" in e.message and "no-such-skill" in e.message


def test_a_skill_in_a_repo_override_is_known(repo):
    d = repo / ".factory" / "config" / "overrides" / "skills" / "mine"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: mine\ndescription: x\n---\nx\n")
    wf = load_text(repo, wf_text("  - id: a\n    tasks: [{id: x, skill: mine}]\n"))
    assert wf.stages[0].tasks[0].skill == "mine"


def test_an_unknown_check_is_reported_with_its_path(repo):
    e = fails(repo, wf_text("  - id: a\n    tasks: [{id: x, cmd: [make, test]}]\n    gate: [{check: no-such-check}]\n"))
    assert "stages.a.gate: unknown check 'no-such-check'" in e.message


@pytest.mark.parametrize("key", ["on_fail", "on_conflict"])
def test_an_unknown_goto_is_reported_with_its_path(repo, key):
    e = fails(repo, wf_text(f"  - id: a\n    tasks: [{{id: x, cmd: [make, test]}}]\n    {key}: {{goto: ghost, max: 1}}\n"))
    assert f"stages.a.{key}.goto: goto 'ghost' is not a stage" in e.message


def test_an_unknown_on_reject_goto_is_reported_with_its_path(repo):
    e = fails(repo, wf_text("  - id: a\n    tasks: [{id: x, cmd: [make, test]}]\n    on_reject: {goto: ghost}\n"))
    assert "stages.a.on_reject.goto: goto 'ghost' is not a stage" in e.message


def test_every_problem_is_listed_in_one_error(repo):
    e = fails(repo, wf_text(
        "  - id: a\n    tasks: [{id: x, skill: nope}]\n    gate: [{check: nope}]\n    on_fail: {goto: nope, max: 1}\n"))
    assert "unknown check" in e.message and "'nope' is not a stage" in e.message and "stages.a.tasks.x" in e.message


def test_a_problem_names_the_file(repo):
    e = fails(repo, wf_text("  - {id: a, needs: [ghost], tasks: [{id: x, cmd: [make, test]}]}\n"))
    assert str(repo / ".factory" / "config" / "workflows" / "t.yaml") in e.message


def test_validate_workflow_returns_problems_as_a_list(repo):
    wf = load_workflow(repo, CFG, "chore")
    wf.stages[0].on_fail.goto = "ghost"
    problems = validate_workflow(wf, CFG)
    assert [type(p) for p in problems] == [Problem]
    assert "ghost" in problems[0].message and problems[0].hint


# ---- schema and shape rules ----

def test_a_schema_error_names_the_path_and_the_line(repo):
    text = wf_text("  - id: a\n    tasks: [{id: x, cmd: [make, test]}]\n    join: sometimes\n")
    e = fails(repo, text)
    assert "stages.0.join" in e.message
    assert f".yaml:{_line_of(text, 'join: sometimes')}:" in e.message


def test_an_unknown_key_is_refused(repo):
    e = fails(repo, wf_text("  - id: a\n    tasks: [{id: x, cmd: [make, test], colour: red}]\n"))
    assert "colour" in e.message


def test_a_command_written_as_a_string_is_refused_with_the_list_form(repo):
    text = wf_text("  - id: a\n    tasks: [{id: x, cmd: make test}]\n")
    e = fails(repo, text)
    assert "a command is a string" in e.message and e.hint == "write the command as a list, such as cmd: [make, test]"
    assert f".yaml:{_line_of(text, 'cmd: make test')}:" in e.message


def test_a_gate_command_and_join_cmd_as_strings_are_refused(repo):
    e = fails(repo, wf_text("  - id: a\n    tasks: [{id: x, cmd: [make, test]}]\n    gate: [{cmd: make build}]\n",
                            header="join_cmd: npm install\n"))
    assert "stages.0.gate.0.cmd" in e.message and "join_cmd" in e.message


def test_a_task_needs_exactly_one_of_skill_and_cmd(repo):
    e = fails(repo, wf_text("  - id: a\n    tasks: [{id: x}, {id: y, skill: fix, cmd: [make, test]}]\n"))
    assert "stages.a.tasks.x" in e.message and "stages.a.tasks.y" in e.message


def test_duplicate_stage_and_task_ids_are_refused(repo):
    e = fails(repo, wf_text("  - {id: a, tasks: [{id: x, cmd: [make, test]}]}\n  - {id: a, tasks: [{id: x, cmd: [make, test]}]}\n"))
    assert "stage id 'a' is used twice" in e.message and "task id 'x' is used twice" in e.message


def test_a_quorum_larger_than_the_task_count_is_refused(repo):
    e = fails(repo, wf_text("  - {id: a, join: 'quorum:3', tasks: [{id: x, cmd: [make, test]}]}\n"))
    assert "quorum:3" in e.message


def test_a_name_that_differs_from_the_file_is_refused(repo):
    write(repo, "other", wf_text("  - {id: a, tasks: [{id: x, cmd: [make, test]}]}\n"))
    with pytest.raises(FactoryError) as e:
        load_workflow(repo, CFG, "other")
    assert "does not match the file name 'other'" in e.value.message


def test_yaml_off_is_a_string_not_a_boolean(repo):
    wf = load_text(repo, wf_text("  - id: a\n    tasks: [{id: x, skill: fix, helpers: {mode: off}}]\n"))
    assert wf.stages[0].tasks[0].helpers.mode == "off"


# ---- criterion 3: overlapping write scopes ----

PARALLEL = ("  - id: a\n    tasks:\n"
            "      - {{id: x, skill: fix, scope: [{p}]}}\n"
            "      - {{id: y, skill: fix, scope: [{q}]{needs}}}\n")


def parallel(p: str, q: str, needs: str = "") -> str:
    return PARALLEL.format(p=p, q=q, needs=needs)


def test_two_parallel_tasks_with_overlapping_scopes_fail(repo):
    e = fails(repo, wf_text(parallel('"src/**"', '"src/api/**"')))
    assert "stages.a.tasks.x and stages.a.tasks.y can run together" in e.message
    assert "'src/**'" in e.message and "'src/api/**'" in e.message


def test_disjoint_scopes_pass(repo):
    load_text(repo, wf_text(parallel('"services/api/**"', '"web/**"')))


def test_a_needs_between_the_tasks_lifts_the_overlap(repo):
    load_text(repo, wf_text(parallel('"src/**"', '"src/api/**"', ", needs: [x]")))


def test_a_transitive_needs_lifts_the_overlap(repo):
    load_text(repo, wf_text(
        "  - id: a\n    tasks:\n"
        "      - {id: x, skill: fix, scope: [\"src/**\"]}\n"
        "      - {id: m, cmd: [make, test], needs: [x]}\n"
        "      - {id: y, skill: fix, scope: [\"src/api/**\"], needs: [m]}\n"))


def test_tasks_in_stages_ordered_by_needs_do_not_overlap(repo):
    load_text(repo, wf_text(
        "  - {id: a, tasks: [{id: x, skill: fix, scope: [\"src/**\"]}]}\n"
        "  - {id: b, needs: [a], tasks: [{id: y, skill: fix, scope: [\"src/**\"]}]}\n"))


def test_tasks_in_unordered_stages_do_overlap(repo):
    e = fails(repo, wf_text(
        "  - {id: a, tasks: [{id: x, skill: fix, scope: [\"src/**\"]}]}\n"
        "  - {id: b, tasks: [{id: y, skill: fix, scope: [\"src/**\"]}]}\n"))
    assert "stages.a.tasks.x and stages.b.tasks.y" in e.message


def test_a_literal_file_in_shared_files_is_exempt(repo):
    text = wf_text(parallel('"web/src/routes.ts"', '"web/src/routes.ts"'), header="shared_files: {\"web/src/routes.ts\": x}\n")
    load_text(repo, text)


def test_a_literal_file_inside_a_glob_is_exempt_only_when_listed(repo):
    stages = parallel('"web/**"', '"web/src/routes.ts"')
    e = fails(repo, wf_text(stages))
    assert "'web/**'" in e.message and "'web/src/routes.ts'" in e.message
    load_text(repo, wf_text(stages, header="shared_files: {\"web/src/routes.ts\": x}\n"))


def test_two_globs_are_reported_even_when_a_shared_file_matches_both(repo):
    e = fails(repo, wf_text(parallel('"web/**"', '"web/src/**"'), header="shared_files: {\"web/src/routes.ts\": x}\n"))
    assert "overlapping scopes" in e.message


def test_a_shared_file_owner_must_be_a_task(repo):
    e = fails(repo, wf_text("  - id: a\n    tasks: [{id: x, cmd: [make, test]}]\n", header="shared_files: {\"f.ts\": ghost}\n"))
    assert "shared_files.f.ts: owner 'ghost' is not a task" in e.message


def test_a_task_with_no_scope_is_not_checked(repo):
    load_text(repo, wf_text("  - id: a\n    tasks: [{id: x, skill: fix}, {id: y, skill: fix, scope: [\"src/**\"]}]\n"))


def test_the_bug_fix_workflow_passes_the_scope_rule_because_frontend_needs_backend(repo):
    wf = load_workflow(repo, CFG, "bug-fix")
    assert [p for p in validate_workflow(wf, CFG) if "overlapping" in p.message] == []


# ---- criterion 5: expand_helpers ----

def task(mode="auto", hints=("api-code", "tests"), out="backend.json") -> TaskSpec:
    return TaskSpec(id="backend", skill="fix", cmd=None, run=None, scope=["services/api/**"], deny=["x/**"],
                    needs=["plan"], helpers=HelperPolicy(mode=mode, max=2, split_hints=list(hints), timeout_minutes=7),
                    out=out, timeout_minutes=30, retries=2, model="m", when=None)


def test_expand_helpers_native_returns_the_task_itself():
    t = task()
    assert expand_helpers(t, "native") == [t]


def test_expand_helpers_none_returns_one_sibling_per_hint():
    t = task()
    siblings = expand_helpers(t, "none")
    assert [s.id for s in siblings] == ["backend-api-code", "backend-tests"]
    assert [s.out for s in siblings] == ["backend-api-code.json", "backend-tests.json"]
    for s in siblings:
        assert s.skill == "fix" and s.scope == t.scope and s.deny == t.deny and s.needs == t.needs
        assert s.timeout_minutes == 30 and s.retries == 2 and s.model == "m"
        assert s.helpers.mode == "off" and s.helpers.split_hints == [] and s.helpers.max == 0


def test_expand_helpers_with_mode_off_returns_siblings_even_on_a_native_harness():
    siblings = expand_helpers(task(mode="off"), "native")
    assert [s.id for s in siblings] == ["backend-api-code", "backend-tests"]


def test_expand_helpers_with_no_hints_returns_the_task_whatever_the_harness():
    t = task(hints=())
    assert expand_helpers(t, "none") == [t]
    assert expand_helpers(task(mode="off", hints=()), "native")[0].id == "backend"


def test_expand_helpers_does_not_change_the_input():
    t = task()
    before = (t.id, t.out, t.helpers.mode, list(t.helpers.split_hints))
    expand_helpers(t, "none")
    assert (t.id, t.out, t.helpers.mode, list(t.helpers.split_hints)) == before


def test_sibling_artifact_name_without_an_extension():
    assert expand_helpers(task(out="report"), "none")[0].out == "report-api-code"
    assert expand_helpers(task(out=None), "none")[0].out is None


def test_expanded_siblings_share_the_parent_scope_and_the_scope_rule_reports_them(repo):
    """Siblings run in parallel with the parent's scope, so validation must treat them as overlapping."""
    stage = Stage(id="fix", needs=[], tasks=expand_helpers(task(), "none"), tasks_from=None, join="all", gate=[],
                  on_fail=None, on_conflict=None, approval="none", on_reject=None, sync_base=False, source="workflow")
    wf = load_workflow(repo, CFG, "chore")
    wf.stages = [stage]
    assert any("overlapping" in p.message for p in validate_workflow(wf, CFG))


# ---- criterion 6: tasks_from ----

def gather_stage() -> Stage:
    return Stage(id="gather", needs=["scope"], tasks=[], tasks_from="questions.json", join="all", gate=[], on_fail=None,
                 on_conflict=None, approval="none", on_reject=None, sync_base=False, source="workflow")


def artifact(tmp_path, doc) -> Path:
    p = tmp_path / "questions.json"
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    return p


def test_tasks_from_builds_one_task_per_item(tmp_path):
    p = artifact(tmp_path, [{"id": "q1", "skill": "gather", "helpers": {"mode": "off"}, "timeout_minutes": 20},
                            {"id": "q2", "skill": "gather", "out": "q2.json"}])
    tasks = expand_tasks_from(gather_stage(), p)
    assert [t.id for t in tasks] == ["q1", "q2"]
    assert tasks[0].timeout_minutes == 20 and tasks[0].helpers.mode == "off" and tasks[1].out == "q2.json"
    assert all(isinstance(t, TaskSpec) for t in tasks)


def test_tasks_from_with_an_empty_list_gives_no_tasks(tmp_path):
    assert expand_tasks_from(gather_stage(), artifact(tmp_path, [])) == []


# ---- owner decision D2 (ADR 2026-11-21-research-questions-use-a-task-template): plain questions plus a template ----

def templated_gather_stage() -> Stage:
    return Stage(id="gather", needs=["scope"], tasks=[], tasks_from="questions.json", join="all", gate=[], on_fail=None,
                 on_conflict=None, approval="none", on_reject=None, sync_base=False, source="workflow",
                 task_template={"skill": "gather", "helpers": {"mode": "off"}, "timeout_minutes": 20})


def test_each_plain_question_becomes_a_task_built_from_the_template(tmp_path):
    p = artifact(tmp_path, [{"id": "q1", "question": "What does the vendor charge per seat?"},
                            {"id": "q2", "question": "Which regions is it available in?"}])
    tasks = expand_tasks_from(templated_gather_stage(), p)
    assert [t.id for t in tasks] == ["q1", "q2"]
    assert all(t.skill == "gather" and t.timeout_minutes == 20 and t.helpers.mode == "off" for t in tasks)


def test_a_question_can_override_a_template_setting(tmp_path):
    p = artifact(tmp_path, [{"id": "q1", "question": "Q?", "timeout_minutes": 45}])
    (task,) = expand_tasks_from(templated_gather_stage(), p)
    assert task.timeout_minutes == 45 and task.skill == "gather"


def test_a_question_list_with_no_template_is_refused_with_the_fix_named(tmp_path):
    with pytest.raises(FactoryError) as e:
        expand_tasks_from(gather_stage(), artifact(tmp_path, [{"id": "q1", "question": "Q?"}]))
    assert e.value.code == "config.invalid"
    assert "task_template" in e.value.message or "task_template" in (e.value.hint or "")


def test_a_templated_question_with_no_question_text_is_refused(tmp_path):
    with pytest.raises(FactoryError) as e:
        expand_tasks_from(templated_gather_stage(), artifact(tmp_path, [{"id": "q1"}]))
    assert e.value.code == "config.invalid" and "question" in e.value.message


RESEARCH = """\
sink: doc
policy: {write: false}
stages:
  - id: scope
    tasks: [{id: questions, skill: scope, out: questions.json}]
    approval: human
  - id: gather
    needs: [scope]
    tasks_from: questions.json
    task_template: %s
    join: all
"""


def test_the_spec_research_stage_with_a_task_template_loads(repo):
    wf = load_text(repo, RESEARCH % "{skill: gather, helpers: {mode: off}, timeout_minutes: 20}", "research")
    gather = next(s for s in wf.stages if s.id == "gather")
    assert gather.task_template == {"skill": "gather", "helpers": {"mode": "off"}, "timeout_minutes": 20}


def test_a_template_that_is_not_a_valid_task_is_refused_when_the_workflow_loads(repo):
    err = fails(repo, RESEARCH % "{skill: gather, colour: red}", "research")
    assert "task_template" in err.message


def test_a_template_on_a_stage_without_tasks_from_is_refused(repo):
    text = "stages:\n  - id: only\n    tasks: [{id: a, skill: gather}]\n    task_template: {skill: gather}\n"
    err = fails(repo, text, "lonely")
    assert "task_template" in err.message and "tasks_from" in err.message


@pytest.mark.parametrize("bad,needle", [
    ([{"id": "q1", "skill": "gather", "colour": "red"}], "item 0"),
    ([{"skill": "gather"}], "item 0"),
    ([{"id": "q1", "skill": "gather"}, {"id": "q2", "cmd": "make test"}], "item 1: cmd"),
    ([{"id": "q1", "skill": "gather", "helpers": {"mode": "loud"}}], "helpers.mode"),
    ([{"id": "Q 1", "skill": "gather"}], "item 0: id"),
    ([{"id": "q1"}], "exactly one of skill and cmd"),
    ([{"id": "q1", "skill": "gather"}, {"id": "q1", "skill": "gather"}], "task id 'q1' is used twice"),
    ([{"id": "q1", "skill": "gather", "needs": ["ghost"]}], "unknown task 'ghost'"),
    ([{"id": "a", "skill": "gather", "needs": ["b"]}, {"id": "b", "skill": "gather", "needs": ["a"]}], "needs cycle"),
    ([{"id": "a", "skill": "gather", "scope": ["x/**"]}, {"id": "b", "skill": "gather", "scope": ["x/y/**"]}],
     "overlapping scopes"),
    ({"id": "q1", "skill": "gather"}, "must be a JSON array"),
])
def test_generated_tasks_that_fail_the_workflow_schema_are_refused(tmp_path, bad, needle):
    with pytest.raises(FactoryError) as e:
        expand_tasks_from(gather_stage(), artifact(tmp_path, bad))
    assert e.value.code == "config.invalid" and e.value.kind == "fail_fast"
    assert needle in e.value.message
    assert "questions.json" in e.value.message and "gather" in e.value.message


def test_a_missing_or_unparsable_artifact_is_refused(tmp_path):
    with pytest.raises(FactoryError) as e:
        expand_tasks_from(gather_stage(), tmp_path / "absent.json")
    assert "cannot read the generated task list" in e.value.message
    with pytest.raises(FactoryError) as e:
        expand_tasks_from(gather_stage(), artifact(tmp_path, "{not json"))
    assert "cannot read the generated task list" in e.value.message


def test_a_stage_with_tasks_from_loads(repo):
    wf = load_text(repo, wf_text(
        "  - id: scope\n    tasks: [{id: questions, skill: scope, out: questions.json}]\n"
        "  - id: gather\n    needs: [scope]\n    tasks_from: questions.json\n"))
    gather = wf.stages[1]
    assert gather.tasks_from == "questions.json" and gather.tasks == []


def test_a_stage_needs_tasks_or_tasks_from(repo):
    e = fails(repo, wf_text("  - id: a\n"))
    assert "stages.0" in e.message


# ---- the shared schema files stay in step ----

def test_the_workflow_schema_is_a_valid_draft_2020_12_schema():
    import jsonschema
    jsonschema.Draft202012Validator.check_schema(json.loads((KIT / "schemas" / "workflow.schema.json").read_text()))

