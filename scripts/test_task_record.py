"""Run from the repo root: python3 -I -m pytest scripts/test_task_record.py (or with uv: uv run --with pytest ...)."""
import importlib.util
import json
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location("task_record", Path(__file__).with_name("task-record.py"))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)


def line(**kw):
    return json.dumps(kw)


def assistant(ts, mid, stop, usage, content=(), model="m1"):
    msg = {"id": mid, "model": model, "stop_reason": stop, "usage": usage, "content": list(content)}
    return line(type="assistant", timestamp=ts, message=msg)


def user_text(ts, text):
    return line(type="user", timestamp=ts, message={"role": "user", "content": text})


def tool_use(tid, name):
    return {"type": "tool_use", "id": tid, "name": name, "input": {}}


def tool_result(ts, tid, decision=None):
    extra = {"permissionDecision": decision} if decision else {}
    return line(type="user", timestamp=ts, message={"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}, **extra)


U = {"input_tokens": 2, "output_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000}


def write(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n")
    return p


def test_tokens_count_each_message_once_even_when_logged_once_per_content_block(tmp_path):
    p = write(tmp_path, "s.jsonl", [
        assistant("2026-11-23T10:00:00Z", "a", "tool_use", U, [{"type": "text", "text": "x"}]),
        assistant("2026-11-23T10:00:01Z", "a", "tool_use", U, [tool_use("t1", "Bash")]),
        assistant("2026-11-23T10:00:02Z", "b", "end_turn", U),
    ])
    s = tr.read_session(p, [])
    assert s["tokens"]["output"] == 20
    assert s["tokens"]["cache_read"] == 2000


def test_waiting_is_the_gap_between_a_finished_turn_and_the_next_prompt(tmp_path):
    p = write(tmp_path, "s.jsonl", [
        user_text("2026-11-23T10:00:00Z", "go"),
        assistant("2026-11-23T10:10:00Z", "a", "end_turn", U),
        user_text("2026-11-23T10:40:00Z", "continue"),
        assistant("2026-11-23T10:41:00Z", "b", "end_turn", U),
    ])
    s = tr.read_session(p, [])
    assert s["wall_s"] == 41 * 60
    assert s["wait_turn_s"] == 30 * 60
    assert s["user_prompts"] == 2


def test_a_question_and_a_prompted_permission_are_waits_but_an_auto_allowed_one_is_not(tmp_path):
    auto = {"decision": "accept", "source": "config"}
    asked = {"decision": "accept", "source": "user_temporary"}
    p = write(tmp_path, "s.jsonl", [
        assistant("2026-11-23T10:00:00Z", "a", "tool_use", U, [tool_use("q", "AskUserQuestion")]),
        tool_result("2026-11-23T10:05:00Z", "q"),
        assistant("2026-11-23T10:05:10Z", "b", "tool_use", U, [tool_use("p", "Bash")]),
        tool_result("2026-11-23T10:05:40Z", "p", asked),
        assistant("2026-11-23T10:06:00Z", "c", "tool_use", U, [tool_use("c", "Bash")]),
        tool_result("2026-11-23T10:06:05Z", "c", auto),
    ])
    s = tr.read_session(p, [])
    assert s["questions"] == 1
    assert s["wait_question_s"] == 300
    assert s["permission_prompts"] == 1
    assert s["wait_permission_s"] == 30


def test_subagent_tokens_are_counted_apart_from_the_main_session(tmp_path):
    main = write(tmp_path, "s.jsonl", [assistant("2026-11-23T10:00:00Z", "a", "end_turn", U)])
    sub = write(tmp_path, "agent-1.jsonl", [assistant("2026-11-23T10:00:01Z", "s1", "end_turn", U)])
    s = tr.read_session(main, [sub])
    assert s["tokens"]["output"] == 10
    assert s["subagent_tokens"]["output"] == 10


def test_changed_files_are_sorted_into_product_spec_and_process():
    kinds = {p: tr.classify(p) for p in [
        "factory/engine/factory_engine/engine.py", "factory/workflows/bug-fix.yaml", "docs/design/modules/06-engine-core.md",
        "docs/tasks.md", "docs/decisions.md", "scripts/docs-check/records.py", "AGENTS.md", "factory/skills/own/fix/SKILL.md",
        "docs/retro/feat-x.json",
    ]}
    assert kinds["factory/engine/factory_engine/engine.py"] == "product"
    assert kinds["factory/workflows/bug-fix.yaml"] == "product"
    assert kinds["docs/design/modules/06-engine-core.md"] == "spec"
    assert kinds["docs/tasks.md"] == kinds["docs/decisions.md"] == kinds["AGENTS.md"] == "process"
    assert kinds["scripts/docs-check/records.py"] == "process"
    assert kinds["factory/skills/own/fix/SKILL.md"] == "product"
    assert kinds["docs/retro/feat-x.json"] is None


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def test_git_side_counts_decision_trailers_adrs_and_lines_by_kind(tmp_path):
    repo = tmp_path / "r"
    (repo / "docs/adr").mkdir(parents=True)
    (repo / "factory/engine").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "a@b")
    _git(repo, "config", "user.name", "a")
    (repo / "docs/decisions.md").write_text("# d\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feat/x")
    (repo / "factory/engine/a.py").write_text("a\nb\nc\n")
    (repo / "docs/adr/2026-11-23-x.md").write_text("adr\n")
    (repo / "docs/decisions.md").write_text("# d\n- 2026-11-23 `x`: chose a over b. Undo: c.\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "work", "-m", "Agent-Run: r1\nDecision: x")
    g = tr.read_git(repo, "main")
    assert g["commits"] == 1
    assert g["decision_trailers"] == 1
    assert g["adrs_added"] == 1
    assert g["decision_lines_added"] == 1
    assert g["lines"]["product"] == 3
    assert g["lines"]["process"] == 2
    assert g["agent_runs"] == ["r1"]


def test_report_totals_every_record_in_the_folder(tmp_path):
    for n, out in (("a", 100), ("b", 50)):
        rec = {"task": n, "wall_s": 3600, "wait_s": 1800, "tokens": {"output": out, "input": 1, "cache_creation": 0, "cache_read": 0},
               "subagent_tokens": {"output": 0, "input": 0, "cache_creation": 0, "cache_read": 0},
               "decisions": {"questions": 2, "trailers": 1, "adrs_added": 0, "lines_added": 1},
               "lines": {"product": 30, "spec": 10, "process": 60}}
        (tmp_path / f"{n}.json").write_text(json.dumps(rec))
    text = tr.render_report(tr.load_records(tmp_path))
    assert "TOTAL" in text
    assert "2h00m" in text
    assert "60%" in text
