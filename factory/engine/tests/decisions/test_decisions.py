"""Module 11 acceptance criteria, decision file half: request, record, evaluate, reopen, and the gate checks."""

import pytest
import yaml

from factory_engine import decisions as D
from factory_engine import state
from factory_engine.errors import FactoryError
from factory_engine.types import GateContext, GateSpec, StageState
from factory_engine.validate import validate

from conftest import architect_packet, decision, option, set_run, without


def events(run, type_=None):
    return [e for e in state.read_events(run.run_dir) if type_ is None or e.type == type_]


def file_doc(run, stage="architecture", visit=1):
    return yaml.safe_load(D.decision_path(run.run_dir, stage, visit).read_text())


def stop(run, packet=None, stage="architecture", kind="decision"):
    return D.request(run.run_dir, stage, 1, kind=kind, packet=packet or architect_packet())


def answer(run, sha, choices, *, stage="architecture", **kw):
    return D.record(run.run_dir, stage, 1, packet_sha=sha, choices=choices, by=kw.pop("by", "me"),
                    channel=kw.pop("channel", "cli"), **kw)


def edit_packet(run, stage="architecture"):
    """Change the packet on disk by hand, the way a stray edit would."""
    path = D.decision_path(run.run_dir, stage, 1)
    doc = yaml.safe_load(path.read_text())
    doc["packet"]["decisions"][0]["why"] = "Edited by hand."
    path.write_text(yaml.safe_dump(doc, sort_keys=False))


def hand_edit(run, stage, **decision_fields):
    """Change the decision block by hand, the editor route."""
    path = D.decision_path(run.run_dir, stage, 1)
    doc = yaml.safe_load(path.read_text())
    doc["decision"].update(decision_fields)
    path.write_text(yaml.safe_dump(doc, sort_keys=False))


# --- every stop kind writes a valid decision file ---

@pytest.mark.parametrize("kind,stage,options", [
    ("approval", "propose", {"approve", "rework", "reject"}),
    ("blocked", "verify", {"retry", "abort"}),
])
def test_engine_template_stops_write_a_valid_decision_file(run, kind, stage, options):
    sha = D.request(run.run_dir, stage, 1, kind=kind)
    doc = file_doc(run, stage)
    validate(doc, "decision")
    assert doc["packet"]["sha"] == sha == D.hash_packet(doc["packet"])
    assert {o["id"] for o in doc["packet"]["decisions"][0]["options"]} == options
    assert doc["decision"]["status"] == "pending"
    assert D.page_path(run.run_dir, stage, 1).is_file()


def test_approval_packet_offers_approve_rework_and_reject(run):
    D.request(run.run_dir, "propose", 1, kind="approval")
    ids = [o["id"] for o in file_doc(run, "propose")["packet"]["decisions"][0]["options"]]
    assert ids == ["approve", "rework", "reject"]


def test_triage_stop_offers_the_candidate_workflows(run):
    packet = D.triage_packet([("bug-fix", "Bug fix", "It describes a defect"),
                              ("feature", "Feature", "It asks for new behavior")])
    D.request(run.run_dir, "_triage", 1, kind="triage", packet=packet)
    doc = file_doc(run, "_triage")
    validate(doc, "decision")
    assert [o["id"] for o in doc["packet"]["decisions"][0]["options"]] == ["bug-fix", "feature"]
    assert D.kind_of(doc["packet"]) == "triage"


def test_architecture_stop_writes_the_skills_packet(run):
    stop(run)
    doc = file_doc(run)
    validate(doc, "decision")
    assert [d["id"] for d in doc["packet"]["decisions"]] == ["D1", "D2"]
    assert D.kind_of(doc["packet"]) == "decision"


@pytest.mark.parametrize("kind", ["triage", "decision"])
def test_a_stop_that_needs_a_skill_packet_refuses_to_invent_one(run, kind):
    with pytest.raises(FactoryError) as e:
        D.request(run.run_dir, "architecture", 1, kind=kind)
    assert e.value.code == "decision.no_packet"
    assert not D.decision_path(run.run_dir, "architecture", 1).exists()


def test_a_request_logs_decision_requested_and_attention_requested(run):
    sha = D.request(run.run_dir, "propose", 1, kind="approval")
    assert [e.data["packet_sha"] for e in events(run, "decision_requested")] == [sha]
    assert [e.data["kind"] for e in events(run, "attention_requested")] == ["approval"]


def test_requesting_the_same_packet_again_keeps_the_answer_and_logs_nothing_new(run):
    sha = D.request(run.run_dir, "propose", 1, kind="approval")
    D.record(run.run_dir, "propose", 1, packet_sha=sha, choices={"D1": "approve"}, by="me", channel="cli")
    n = len(events(run))
    assert D.request(run.run_dir, "propose", 1, kind="approval") == sha
    assert len(events(run)) == n
    assert file_doc(run, "propose")["decision"]["status"] == "approved"


# --- an architect packet missing a picker field fails validate ---

@pytest.mark.parametrize("path", [
    ("decisions", 0, "context"),
    ("decisions", 0, "options"),
    ("decisions", 0, "recommend"),
    ("decisions", 0, "compare"),
    ("decisions", 0, "why"),
])
def test_an_architect_packet_missing_a_picker_field_fails_validate(run, path):
    bad = without(architect_packet(), *path)
    with pytest.raises(FactoryError) as e:
        D.request(run.run_dir, "architecture", 1, kind="decision", packet=bad)
    assert e.value.code == "config.invalid" and path[-1] in e.value.message
    assert not D.decision_path(run.run_dir, "architecture", 1).exists()


def test_an_option_with_no_flow_fails_validate(run):
    bad = without(architect_packet(), "decisions", 0, "options", 0, "flow")
    with pytest.raises(FactoryError) as e:
        D.request(run.run_dir, "architecture", 1, kind="decision", packet=bad)
    assert "flow" in e.value.message


def test_a_recommendation_that_is_not_an_option_is_refused(run):
    bad = architect_packet(decision(recommend="nope"))
    with pytest.raises(FactoryError) as e:
        D.request(run.run_dir, "architecture", 1, kind="decision", packet=bad)
    assert "recommend" in e.value.message


def test_repeated_decision_ids_are_refused(run):
    with pytest.raises(FactoryError):
        D.request(run.run_dir, "architecture", 1, kind="decision", packet=architect_packet(decision(), decision()))


# --- record: stale sha, bad choices, the lock ---

def test_record_with_a_stale_packet_sha_is_refused_with_a_reopen_hint(run):
    stop(run)
    with pytest.raises(FactoryError) as e:
        answer(run, "deadbeef", {"D1": "opt-a", "D2": "opt-b"})
    assert e.value.code == "decision.stale_packet"
    assert "factory open new-color-q1w2e" in e.value.hint
    assert file_doc(run)["decision"]["status"] == "pending"
    assert [e.data["reason"] for e in events(run, "decision_rejected")] == ["stale packet"]


def test_record_refuses_an_old_sha_after_the_packet_is_replaced(run):
    old = stop(run)
    new = stop(run, architect_packet(decision(), decision("D2", title="Datastore")))
    assert old != new
    with pytest.raises(FactoryError) as e:
        answer(run, old, {"D1": "opt-a", "D2": "opt-b"})
    assert e.value.code == "decision.stale_packet"


@pytest.mark.parametrize("choices,fragment", [
    ({"D1": "opt-z", "D2": "opt-b"}, "opt-z"),
    ({"D1": "opt-a", "D9": "opt-b"}, "D9"),
    ({"D1": "opt-a"}, "D2: no choice"),
])
def test_unknown_or_missing_choices_are_refused_and_the_stop_stays_pending(run, choices, fragment):
    sha = stop(run)
    with pytest.raises(FactoryError) as e:
        answer(run, sha, choices)
    assert e.value.code == "decision.bad_choice" and fragment in e.value.message
    assert file_doc(run)["decision"]["status"] == "pending"
    assert events(run, "decision_rejected")


def test_a_valid_answer_is_approved_and_logged_from_any_channel(run):
    sha = stop(run)
    out = answer(run, sha, {"D1": "opt-a", "D2": "opt-b"}, notes="Keep it simple", by="alice", channel="chat")
    assert (out.status, out.choices, out.notes) == ("approved", {"D1": "opt-a", "D2": "opt-b"}, "Keep it simple")
    dec = file_doc(run)["decision"]
    assert (dec["status"], dec["by"], dec["channel"]) == ("approved", "alice", "chat") and dec["at"]
    types = [e.type for e in events(run) if e.type.startswith(("decision_", "attention_"))]
    assert types == ["decision_requested", "attention_requested", "decision_recorded", "decision_approved",
                     "attention_cleared"]


def test_an_approved_decision_is_locked_until_reopened(run):
    sha = stop(run)
    answer(run, sha, {"D1": "opt-a", "D2": "opt-b"})
    with pytest.raises(FactoryError) as e:
        answer(run, sha, {"D1": "opt-b", "D2": "opt-b"})
    assert e.value.code == "decision.locked" and "factory reopen" in e.value.hint
    D.reopen(run.run_dir, "architecture", 1, by="me")
    assert [e.type for e in events(run)][-2:] == ["decision_reopened", "attention_requested"]
    out = answer(run, sha, {"D1": "opt-b", "D2": "opt-b"})
    assert out.status == "approved" and out.choices["D1"] == "opt-b"


def test_reopening_a_decision_that_is_not_approved_changes_nothing(run):
    stop(run)
    n = len(events(run))
    D.reopen(run.run_dir, "architecture", 1, by="me")
    assert len(events(run)) == n


def test_the_hash_covers_only_the_packet_so_answers_never_break_it(run):
    sha = stop(run)
    answer(run, sha, {"D1": "opt-a", "D2": "opt-b"}, notes="n")
    assert D.hash_packet(file_doc(run)["packet"]) == sha


# --- the not-sure route ---

def test_a_question_answer_returns_the_questions(run):
    sha = stop(run)
    out = answer(run, sha, {"D1": "opt-a"}, questions={"D2": "Can option B add charts later?"}, channel="dashboard")
    assert out.status == "question"
    assert out.questions == {"D2": "Can option B add charts later?"}
    assert file_doc(run)["decision"]["status"] == "question"
    assert not events(run, "decision_approved")


def test_a_revised_packet_after_a_question_is_a_new_request_with_a_new_sha(run):
    sha = stop(run)
    answer(run, sha, {"D1": "opt-a"}, questions={"D2": "Why?"})
    new = stop(run, architect_packet(decision(), decision("D2", why="Because charts can be added later.")))
    assert new != sha
    assert file_doc(run)["decision"]["status"] == "pending"
    assert len(events(run, "decision_requested")) == 2
    assert len(events(run, "decision_invalidated")) == 1


# --- an edited packet ---

def test_editing_the_packet_after_an_answer_gives_decision_invalidated(run):
    sha = stop(run)
    answer(run, sha, {"D1": "opt-a", "D2": "opt-b"})
    edit_packet(run)
    out = D.evaluate(run.run_dir, "architecture", 1)
    assert (out.status, out.code) == ("rejected", "decision.stale_packet")
    assert len(events(run, "decision_invalidated")) == 1


def test_editing_the_packet_before_any_answer_is_a_rejection_not_an_invalidation(run):
    stop(run)
    edit_packet(run)
    out = D.evaluate(run.run_dir, "architecture", 1)
    assert out.status == "rejected"
    assert not events(run, "decision_invalidated")
    assert events(run, "decision_rejected")


def test_record_refuses_an_old_sha_when_the_packet_was_edited_on_disk(run):
    sha = stop(run)
    edit_packet(run)
    with pytest.raises(FactoryError) as e:
        answer(run, sha, {"D1": "opt-a", "D2": "opt-b"})
    assert e.value.code == "decision.stale_packet"


# --- evaluate: the editor route and its outcomes ---

def test_a_decision_filled_in_by_hand_is_evaluated_like_any_other(run):
    stop(run)
    hand_edit(run, "architecture", status="approved", choices={"D1": "opt-a", "D2": "opt-b"}, by="me", channel="file")
    out = D.evaluate(run.run_dir, "architecture", 1)
    assert out.status == "approved" and out.choices == {"D1": "opt-a", "D2": "opt-b"}


def test_a_hand_edit_with_an_unknown_choice_is_rejected_with_a_reason(run):
    stop(run)
    hand_edit(run, "architecture", status="approved", choices={"D1": "opt-z", "D2": "opt-b"})
    out = D.evaluate(run.run_dir, "architecture", 1)
    assert (out.status, out.code) == ("rejected", "decision.bad_choice") and "opt-z" in out.message


def test_a_hand_edit_with_broken_yaml_is_rejected_and_names_the_line(run):
    stop(run)
    D.decision_path(run.run_dir, "architecture", 1).write_text("packet: [unclosed\n")
    out = D.evaluate(run.run_dir, "architecture", 1)
    assert out.status == "rejected" and out.code == "config.invalid" and "line" in out.message


def test_a_hand_edit_that_fails_the_schema_is_rejected(run):
    stop(run)
    hand_edit(run, "architecture", status="maybe")
    assert D.evaluate(run.run_dir, "architecture", 1).status == "rejected"


def test_yaml_words_like_off_and_no_stay_strings_through_an_answer(run):
    """The option ids off and no are YAML 1.1 booleans. The factory loader reads them as text."""
    packet = {"stage": "architecture", "sha": "", "decisions": [decision(
        options=[option("off", "Off"), option("no", "No")], recommend="off",
        compare={"a": "off", "b": "no", "rows": [], "choose_a_if": "x", "choose_b_if": "y"})]}
    sha = stop(run, packet)
    out = answer(run, sha, {"D1": "no"})
    assert out.choices == {"D1": "no"} and out.status == "approved"
    assert file_doc(run)["packet"]["decisions"][0]["options"][1]["id"] == "no"


def test_evaluate_logs_each_outcome_once_per_file_content(run):
    sha = stop(run)
    answer(run, sha, {"D1": "opt-a", "D2": "opt-b"})
    for _ in range(3):
        D.evaluate(run.run_dir, "architecture", 1)
    assert len(events(run, "decision_approved")) == 1
    D.reopen(run.run_dir, "architecture", 1, by="me")
    answer(run, sha, {"D1": "opt-a", "D2": "opt-b"}, notes="second answer")
    assert len(events(run, "decision_approved")) == 2  # new file content: logged again


def test_a_rejected_file_is_logged_once_however_often_it_is_checked(run):
    stop(run)
    hand_edit(run, "architecture", status="approved", choices={"D1": "opt-z", "D2": "opt-b"})
    for _ in range(3):
        D.evaluate(run.run_dir, "architecture", 1)
    assert len(events(run, "decision_rejected")) == 1


def test_evaluating_a_stop_that_was_never_requested_is_pending(run):
    assert D.evaluate(run.run_dir, "propose", 1).status == "pending"


# --- approval and blocked answers map to a route ---

@pytest.mark.parametrize("pick,status", [("approve", "approved"), ("rework", "rework"), ("reject", "reject")])
def test_approval_answers_map_to_approved_rework_or_reject(run, pick, status):
    sha = D.request(run.run_dir, "propose", 1, kind="approval")
    out = answer(run, sha, {"D1": pick}, stage="propose", notes="tighten it")
    assert out.status == status and out.notes == "tighten it"


@pytest.mark.parametrize("pick,status", [("retry", "approved"), ("abort", "reject")])
def test_blocked_answers_map_to_retry_or_abort(run, pick, status):
    sha = D.request(run.run_dir, "verify", 1, kind="blocked")
    assert answer(run, sha, {"D1": pick}, stage="verify").status == status


# --- a new visit gets a new file ---

def test_a_second_visit_gets_its_own_file_and_leaves_the_first_alone(run):
    sha = D.request(run.run_dir, "propose", 1, kind="approval")
    answer(run, sha, {"D1": "approve"}, stage="propose")
    first = D.decision_path(run.run_dir, "propose", 1).read_text()

    D.request(run.run_dir, "propose", 2, kind="approval")
    assert D.decision_path(run.run_dir, "propose", 2).name == "propose.2.yaml"
    assert D.decision_path(run.run_dir, "propose", 1).read_text() == first
    assert D.evaluate(run.run_dir, "propose", 2).status == "pending"  # a fresh approval is needed
    assert D.evaluate(run.run_dir, "propose", 1).status == "approved"


def test_the_latest_visit_is_the_open_one(run):
    r = set_run(run, status="awaiting_approval", stage="propose", stages=[
        StageState("propose", 1, "done", [], "t0", "t1"),
        StageState("propose", 2, "awaiting_approval", [], "t2", None)])
    assert D.latest_visit(r, "propose") == 2
    assert D.latest_visit(r, "never-ran") == 1


# --- gate checks used by module 8 ---

def gate_ctx(run, worktree, stage="propose"):
    r = set_run(run, status="awaiting_approval", stage=stage,
                stages=[StageState(stage, 1, "awaiting_approval", [], "t0", None)])
    return GateContext(run=r, stage=stage, task_id=None, worktree=worktree, task_dir=None, artifact=None,
                       task_base=None, scope=[], deny=[], cfg=None)  # type: ignore[arg-type]


SPEC = GateSpec(kind="check", cmd=None, check="decision-approved", schema=None, args={})


def test_check_approved_passes_only_after_an_approve_answer(run, tmp_path):
    sha = D.request(run.run_dir, "propose", 1, kind="approval")
    ctx = gate_ctx(run, tmp_path)
    assert D.check_approved(SPEC, ctx).passed is False
    answer(run, sha, {"D1": "rework"}, stage="propose")
    assert D.check_approved(SPEC, ctx).passed is False  # rework is not approval
    D.reopen(run.run_dir, "propose", 1, by="me")
    answer(run, sha, {"D1": "approve"}, stage="propose")
    res = D.check_approved(SPEC, ctx)
    assert res.passed and res.gate == "decision-approved"


def test_check_packet_hash_fails_when_the_packet_was_edited(run, tmp_path):
    D.request(run.run_dir, "propose", 1, kind="approval")
    ctx = gate_ctx(run, tmp_path)
    assert D.check_packet_hash(SPEC, ctx).passed
    edit_packet(run, "propose")
    res = D.check_packet_hash(SPEC, ctx)
    assert not res.passed and res.code == "gate.packet_hash_mismatch"


def test_check_packet_hash_fails_when_there_is_no_decision_file(run, tmp_path):
    assert D.check_packet_hash(SPEC, gate_ctx(run, tmp_path)).code == "gate.decision_missing"


def _bare_ctx(worktree):
    return GateContext(run=None, stage="build", task_id=None, worktree=worktree, task_dir=None,  # type: ignore[arg-type]
                       artifact=None, task_base=None, scope=[], deny=[], cfg=None)  # type: ignore[arg-type]


def test_check_build_stack_matches_the_approved_stack(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "18", "vite": "5"}}')
    ctx = _bare_ctx(tmp_path)
    ok = D.check_build_stack(GateSpec("check", None, "build-matches-stack", None, {"require": ["react", "vite"]}), ctx)
    bad = D.check_build_stack(GateSpec("check", None, "build-matches-stack", None, {"require": ["react", "angular"]}), ctx)
    assert ok.passed and not bad.passed and bad.details["missing"] == ["angular"]


def test_check_build_stack_reads_pom_xml_for_a_java_stack(tmp_path):
    (tmp_path / "pom.xml").write_text("<artifactId>spring-boot</artifactId>")
    res = D.check_build_stack(GateSpec("check", None, "build-matches-stack", None, {"require": ["spring-boot"]}),
                              _bare_ctx(tmp_path))
    assert res.passed and res.details["file"] == "pom.xml"


def test_check_build_stack_fails_with_no_build_file(tmp_path):
    res = D.check_build_stack(GateSpec("check", None, "build-matches-stack", None, {"require": ["react"]}),
                              _bare_ctx(tmp_path))
    assert res.code == "gate.build_file_missing"
