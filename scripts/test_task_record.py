"""Run from the repo root: python3 -I -m pytest scripts/test_task_record.py (or with uv: uv run --with pytest ...)."""
import importlib.util
import json
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location("task_record", Path(__file__).with_name("task-record.py"))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

U = {"input_tokens": 2, "output_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000}
ROOT = "/Users/x/orca/workspaces/factory/feat"


def at(s):
    return f"2026-11-23T10:{s // 60:02d}:{s % 60:02d}Z" if s < 3600 else f"2026-11-23T1{1 + (s - 3600) // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}Z"


def asst(s, mid, stop, tools=(), usage=U, text=None):
    content = [{"type": "tool_use", "id": f"{mid}-{i}", "name": n, "input": inp} for i, (n, inp) in enumerate(tools)]
    if text or not content:
        content.insert(0, {"type": "text", "text": text or "ok"})
    return json.dumps({"type": "assistant", "timestamp": at(s), "message": {
        "id": mid, "model": "m1", "stop_reason": stop, "usage": usage, "content": content}})


def prompt(s, text):
    return json.dumps({"type": "user", "timestamp": at(s), "message": {"role": "user", "content": text}})


def result(s, tid, answers=None, source=None, error=False, content="ok"):
    extra = {}
    if answers is not None:
        extra["toolUseResult"] = {"answers": answers}
    if source:
        extra["permissionDecision"] = {"decision": "accept", "source": source}
    return json.dumps({"type": "user", "timestamp": at(s), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": content, "is_error": error}]}, **extra})


def hook(s, event, ms):
    return json.dumps({"type": "attachment", "timestamp": at(s), "attachment": {
        "type": "hook_success", "hookEvent": event, "durationMs": ms}})


def write(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n")
    return p


def bash(cmd):
    return ("Bash", {"command": cmd})


def read(tmp_path, lines, subs=()):
    return tr.read_session(write(tmp_path, "s.jsonl", lines), list(subs))


def test_every_second_lands_in_one_bucket_and_waits_are_told_apart(tmp_path):
    s = read(tmp_path, [
        prompt(0, "go"),
        asst(10, "a", "tool_use", [bash("uv run pytest -q")]), result(70, "a-0"),
        asst(80, "b", "end_turn"),
        prompt(680, "continue"),
        asst(690, "c", "tool_use", [("AskUserQuestion", {"questions": []})]), result(990, "c-0", answers={}),
        asst(1000, "d", "end_turn"),
        prompt(3000, "back"),
        asst(3010, "e", "end_turn"),
    ])
    b = s["time"]["buckets"]
    assert s["time"]["wall_s"] == 3010
    assert b["run_tests"] == 10 + 60
    assert b["wait_reply"] == 600
    assert b["wait_question"] == 300
    assert b["ask_owner"] == 10
    assert b["think_reply"] == 10 + 10 + 10
    assert b["away"] == 2000
    assert sum(b.values()) == 3010


def test_a_message_split_over_entries_opens_every_tool_it_holds(tmp_path):
    # Claude Code logs one message as several entries that share its id. Each entry has one content block, so a
    # second tool use in the same message arrives on its own entry and must open its own span.
    first = json.dumps({"type": "assistant", "timestamp": at(10), "message": {
        "id": "m", "model": "m1", "stop_reason": "tool_use", "usage": U,
        "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "uv run pytest"}}]}})
    second = json.dumps({"type": "assistant", "timestamp": at(10), "message": {
        "id": "m", "model": "m1", "stop_reason": "tool_use", "usage": U,
        "content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "uv run pytest"}}]}})
    s = read(tmp_path, [prompt(0, "go"), first, second,
                        result(70, "t1"), result(130, "t2"), asst(131, "z", "end_turn")])
    assert s["time"]["buckets"]["run_tests"] == 10 + 60 + 60


def test_a_background_notification_gap_is_machine_wait_not_owner_wait(tmp_path):
    s = read(tmp_path, [
        prompt(0, "go"), asst(10, "a", "end_turn"),
        prompt(400, "<task-notification><task-id>x</task-id></task-notification>"),
        asst(410, "b", "end_turn"),
    ])
    assert s["time"]["buckets"]["wait_machine"] == 390
    assert "wait_reply" not in s["time"]["buckets"]


def test_time_spent_writing_a_message_goes_to_the_activity_that_message_performs(tmp_path):
    # The 10s before the edit is the model writing the edit, so it is building product, not thinking.
    edit = ("Edit", {"file_path": f"{ROOT}/factory/engine/factory_engine/engine.py"})
    s = read(tmp_path, [
        prompt(0, "go"),
        asst(10, "a", "tool_use", [edit]), result(11, "a-0"),
        asst(20, "b", "tool_use", [bash("uv run pytest")]), result(80, "b-0"),
        asst(85, "c", "end_turn"),
    ])
    b = s["time"]["buckets"]
    assert b["build_product"] == 10 + 1
    assert b["run_tests"] == 60 + 9
    assert b["think_reply"] == 5


def test_commit_and_push_time_is_the_tool_span_so_hook_cost_is_visible(tmp_path):
    s = read(tmp_path, [
        prompt(0, "go"),
        asst(5, "a", "tool_use", [bash("git add -A && git commit -q -m x")]), result(25, "a-0"),
        asst(30, "b", "tool_use", [bash("git push -u origin HEAD")]), result(36, "b-0"),
        asst(40, "c", "end_turn"),
    ])
    b = s["time"]["buckets"]
    assert b["commit_hooks"] == 5 + 20
    assert b["push_hooks"] == 5 + 6
    assert b["think_reply"] == 4


def test_a_permission_the_config_did_not_allow_is_owner_wait(tmp_path):
    s = read(tmp_path, [
        prompt(0, "go"),
        asst(5, "a", "tool_use", [bash("rm -rf x")]), result(65, "a-0", source="user_temporary"),
        asst(70, "b", "tool_use", [bash("ls")]), result(71, "b-0", source="config"),
        asst(72, "c", "end_turn"),
    ])
    assert s["time"]["buckets"]["wait_permission"] == 60


def test_tokens_count_each_message_once_and_split_by_activity(tmp_path):
    edit = ("Edit", {"file_path": f"{ROOT}/factory/engine/factory_engine/engine.py"})
    note = ("Edit", {"file_path": f"{ROOT}/docs/tasks.md"})
    s = read(tmp_path, [
        prompt(0, "go"),
        asst(5, "a", "tool_use", [edit]), asst(6, "a", "tool_use", [edit], text="again"), result(8, "a-0"),
        asst(9, "b", "tool_use", [note]), result(10, "b-0"),
        asst(11, "c", "end_turn"),
    ])
    t = s["tokens"]
    assert t["main"]["output"] == 30
    assert t["by_activity"]["build_product"] == {"new": 112, "reread": 1000}
    assert t["by_activity"]["edit_records"]["new"] == 112
    assert t["by_activity"]["think_reply"]["new"] == 112


def test_subagent_tokens_are_counted_apart_but_share_the_activity_table(tmp_path):
    sub = write(tmp_path, "agent-1.jsonl", [asst(1, "s1", "end_turn")])
    s = read(tmp_path, [prompt(0, "go"), asst(5, "a", "end_turn")], [sub])
    assert s["tokens"]["subagent"]["output"] == 10
    assert s["tokens"]["main"]["output"] == 10
    assert s["tokens"]["by_activity"]["think_reply"]["new"] == 224


def test_tools_map_to_activities():
    cases = {
        ("Bash", "git -C /x commit -m y"): "commit_hooks",
        ("Bash", "cd /x && git push origin HEAD"): "push_hooks",
        ("Bash", "gh pr create --fill"): "github",
        ("Bash", "cd factory/engine && uv run pytest -n 8"): "run_tests",
        ("Bash", "python3 -I scripts/docs-check/records.py ."): "records_checks",
        ("Bash", "sleep 240"): "wait_machine",
        ("Bash", "git log --oneline"): "investigate",
        ("Read", ""): "investigate",
        ("AskUserQuestion", ""): "ask_owner",
        ("Agent", ""): "delegate",
    }
    for (name, cmd), want in cases.items():
        assert tr.tool_activity(name, {"command": cmd}) == want, (name, cmd)
    skill = lambda n: tr.tool_activity("Skill", {"skill": n})
    assert skill("decision-page") == "decision_pages"
    assert skill("revise-spec") == "records_checks"


def test_edits_are_sorted_by_where_the_file_lives():
    edit = lambda p: tr.tool_activity("Edit", {"file_path": p})
    assert edit(f"{ROOT}/factory/engine/factory_engine/engine.py") == "build_product"
    assert edit(f"{ROOT}/factory/skills/own/fix/SKILL.md") == "build_product"
    assert edit(f"{ROOT}/docs/design/modules/06-engine-core.md") == "write_spec"
    assert edit(f"{ROOT}/docs/decisions.md") == "edit_records"
    assert edit(f"{ROOT}/AGENTS.md") == "edit_records"
    assert edit("docs/retro/x.json") == "edit_records"
    assert edit("/Users/x/.claude/projects/memory/m.md") == "investigate"
    assert edit("/Users/x/Developer/factory/factory/engine/a.py") == "build_product"


def test_a_message_takes_its_most_admin_activity():
    assert tr.message_activity([]) == "think_reply"
    assert tr.message_activity([("Read", {}), ("Edit", {"file_path": "docs/tasks.md"})]) == "edit_records"
    assert tr.message_activity([("Bash", {"command": "sleep 5"})]) == "wait_machine"


def test_a_decision_is_filed_by_category_and_stop_trigger():
    c = tr.classify_decision
    assert c("Token rotation: has the gateway token been rotated?") == {
        "category": "security and ops", "importance": "high", "trigger": "costly-to-reverse"}
    assert c("D5 would reopen a Decisions row in module 8")["importance"] == "high"
    assert c("D5 would reopen a Decisions row in module 8")["trigger"] == "reopens-decision"
    assert c("Move the codex adapter to phase 2 scope")["importance"] == "medium"
    low = c("Which languages get a test task")
    assert (low["category"], low["importance"], low["trigger"]) == ("code", "low", "routine")
    assert c("Scorecard wording for module 5")["category"] == "spec and design"
    assert c("How should tasks.md Log lines be merged?")["category"] == "process and records"


def test_question_answers_are_followed_overridden_or_custom(tmp_path):
    def ask(header, rec_first=True):
        return ("AskUserQuestion", {"questions": [{"question": f"{header}?", "header": header, "options": [
            {"label": "Do A (Recommended)", "description": "x"}, {"label": "Do B", "description": "y"}]}]})
    s = read(tmp_path, [
        prompt(0, "go"),
        asst(1, "a", "tool_use", [ask("One")]), result(2, "a-0", answers={"One?": "Do A (Recommended)"}),
        asst(3, "b", "tool_use", [ask("Two")]), result(4, "b-0", answers={"Two?": "Do B"}),
        asst(5, "c", "tool_use", [ask("Three")]), result(6, "c-0", answers={"Three?": "something else"}),
        asst(7, "d", "end_turn"),
    ])
    out = {d["header"]: d["outcome"] for d in s["owner_decisions"]}
    assert out == {"One": "followed", "Two": "overridden", "Three": "custom"}
    assert all(d["source"] == "question" for d in s["owner_decisions"])


def test_decision_page_answers_are_read_from_pasted_lines_but_not_from_skill_text(tmp_path):
    text = ("Task: apply\n- D1 Task list merge conflicts: Only the merger edits [integrator-writes] (not the recommendation)\n"
            "- D2 Pilot start day: Start now [start-now] (recommended)\n"
            "D3 Scope: NOT SURE. Question: what does it cost?\n"
            "The page makes `D3 <title>: <option name> [<option id>] (recommended)` per card.\n")
    s = read(tmp_path, [prompt(0, text), asst(1, "a", "end_turn"), prompt(9, text), asst(10, "b", "end_turn")])
    got = {(d["id"], d["outcome"]) for d in s["owner_decisions"]}
    assert got == {("D1", "overridden"), ("D2", "followed"), ("D3", "unsure")}
    assert len(s["owner_decisions"]) == 3


def test_human_prompts_are_sorted_by_what_they_cost_in_supervision():
    k = tr.classify_prompt
    assert k("how much longer") == k("is it done?") == k("what is the status?") == k("why is it taking so long?") == "poll"
    assert k("continue") == k("yes") == "approve"
    assert k("push and PR") == k("yes. push and then create PR") == k("commit, PR for me to merge to main") == "deliver"
    assert k("issue #56 pattern is incorrect. it needs to be designed so that it can start earlier") == "steer"
    assert k("work on @docs/design/phase-2.md P2-1") == "instruction"
    assert k("Task: Apply four decisions to the spec") == "handoff"
    assert k("<task-notification><task-id>a</task-id></task-notification>") == "harness"
    assert k("<command-name>/clear</command-name>") == "harness"


def test_friction_counts_errors_interrupts_slow_commands_and_secret_scans(tmp_path):
    scan = "Block Secrets: commit scanned, no secrets found."
    s = read(tmp_path, [
        prompt(0, "go"),
        asst(1, "a", "tool_use", [bash("make slow-thing")]), result(200, "a-0", error=True),
        asst(201, "b", "tool_use", [bash("git commit -q -m x")]), result(204, "b-0", content=scan),
        prompt(210, "[Request interrupted by user]"),
        hook(211, "PreToolUse", 93), hook(212, "PreToolUse", 107), hook(213, "Stop", 1000),
        asst(214, "c", "end_turn"),
    ])
    f = s["friction"]
    assert f["tool_errors"] == 1
    assert f["interrupts"] == 1
    assert f["slow"] == [[199, "make slow-thing"]]
    assert f["secret_scans"] == 1
    assert s["hooks"] == {"PreToolUse": 0.2, "Stop": 1.0}


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def test_git_side_rates_each_agent_decision_by_where_it_was_recorded(tmp_path):
    repo = tmp_path / "r"
    for d in ("docs/adr", "docs/design/modules", "factory/engine"):
        (repo / d).mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "a@b")
    _git(repo, "config", "user.name", "a")
    (repo / "docs/decisions.md").write_text("# d\n")
    (repo / "docs/design/modules/01-x.md").write_text("## Decisions\n\n| Rule | Why | Not chosen | Id |\n| --- | --- | --- | --- |\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feat/x")

    def commit(files, subject, trailer):
        for name, text in files.items():
            (repo / name).write_text(text, encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", subject, "-m", f"Agent-Run: r1\n{trailer}")

    commit({"docs/design/modules/01-x.md": "## Decisions\n\n| Rule | Why | Not chosen | Id |\n| --- | --- | --- | --- |\n| a | b | c | 2026-11-23-big |\n"},
           "spec row", "Decision: 2026-11-23-big")
    commit({"docs/decisions.md": "# d\n- 2026-11-23 `small`: x. Undo: y.\n"}, "log line", "Decision: small")
    commit({"factory/engine/a.py": "a\nb\nc\n"}, "code", "Decision: mid")
    g = tr.read_git(repo, "main")
    got = {d["id"]: d["importance"] for d in g["agent_decisions"]}
    assert got == {"2026-11-23-big": "high", "small": "low", "mid": "medium"}
    assert g["commits"] == 3
    assert g["decision_trailers"] == 3
    assert g["lines"]["product"] == 3
    assert g["agent_runs"] == ["r1"]


def test_a_chained_shell_command_is_not_charged_to_the_hooks_it_contains(tmp_path):
    s = read(tmp_path, [
        prompt(0, "go"),
        asst(5, "a", "tool_use", [bash("cd e && uv run pytest -q && git add -A && git commit -q -m x")]), result(65, "a-0"),
        asst(70, "b", "tool_use", [bash("git commit -q -m y && git push -u origin HEAD && gh pr create --fill")]), result(80, "b-0"),
        asst(85, "c", "end_turn"),
    ])
    b = s["time"]["buckets"]
    assert b["mixed_shell"] == 5 + 60
    assert b["deliver_chain"] == 5 + 10
    assert "commit_hooks" not in b


def test_commands_report_own_time_apart_from_chained_time_and_gh_by_subcommand(tmp_path):
    s = read(tmp_path, [
        prompt(0, "go"),
        asst(5, "a", "tool_use", [bash("gh pr view 5")]), result(8, "a-0"),
        asst(20, "b", "tool_use", [bash("gh pr view 5")]), result(22, "b-0"),
        asst(30, "c", "tool_use", [bash("git push origin HEAD && gh pr create --fill")]), result(40, "c-0"),
        asst(50, "d", "tool_use", [bash("git commit -q -m x")]), result(52, "d-0"),
        asst(60, "e", "end_turn"),
    ])
    c = s["commands"]
    assert c["gh pr view"] == {"calls": 2, "s": 5, "pure_calls": 2, "pure_s": 5}
    assert c["gh"] == {"calls": 3, "s": 15, "pure_calls": 2, "pure_s": 5}
    assert c["git push"] == {"calls": 1, "s": 10, "pure_calls": 0, "pure_s": 0}
    assert c["git commit"] == {"calls": 1, "s": 2, "pure_calls": 1, "pure_s": 2}
    assert s["gh_repeat_reads"] == {"n": 1, "s": 2}


def test_a_reply_gap_is_filed_by_what_the_agent_ended_its_turn_with(tmp_path):
    def turn(start, mid, text):
        return [asst(start, mid, "end_turn", text=text)]
    s = read(tmp_path, [
        prompt(0, "go"),
        *turn(5, "a", "Which option do you want?"), prompt(65, "A"),
        *turn(70, "b", "Opened https://github.com/o/r/pull/9"), prompt(100, "ok"),
        *turn(105, "c", "All 12 tests passed."), prompt(125, "ok"),
        *turn(130, "d", "Still working through the second module."), prompt(190, "ok"),
        *turn(195, "e", "Which option do you want?"), prompt(5000, "back"),
        *turn(5005, "f", "done"),
    ])
    g = s["reply_gaps"]
    assert g["asked"] == {"n": 1, "s": 60}
    assert g["delivered"] == {"n": 1, "s": 30}
    assert g["finished"] == {"n": 1, "s": 20}
    assert g["status"] == {"n": 1, "s": 60}
    assert sum(v["n"] for v in g.values()) == 4


def test_question_waits_are_kept_one_by_one_so_a_few_open_questions_cannot_pose_as_the_total(tmp_path):
    ask = ("AskUserQuestion", {"questions": []})
    s = read(tmp_path, [
        prompt(0, "go"),
        asst(1, "a", "tool_use", [ask]), result(31, "a-0", answers={}),
        asst(32, "b", "tool_use", [ask]), result(3032, "b-0", answers={}),
        asst(3033, "c", "end_turn"),
    ])
    assert s["question_wait_s"] == [30, 3000]


def test_a_question_has_a_theme_and_a_day_so_repeats_and_surges_show():
    t = tr.question_theme
    assert t("Push and open the PR now?") == "push, PR and merge approval"
    assert t("Token rotation: has the gateway token been rotated?") == "token and secret rotation"
    assert t("Stalled ADR: fix it now or record a task?") == "fix now or later"
    assert t("Which file should hold the index?") == "where it lives"
    assert t("Spec wording for module 9") == "spec wording"
    assert t("Something unrelated") == "other"


def _rec(tmp, **over):
    base = {"task": "t", "time": {"wall_s": 0, "buckets": {}}, "tokens": {"main": {}, "subagent": {}, "by_activity": {}},
            "prompts": {}, "owner_decisions": [], "agent_decisions": [], "hooks": {}, "commands": {},
            "reply_gaps": {}, "question_wait_s": [], "gh_repeat_reads": {"n": 0, "s": 0},
            "friction": {"tool_errors": 0, "interrupts": 0, "secret_scans": 0, "slow": []}}
    base.update(over)
    return base


def test_signals_fire_only_on_the_numbers_that_justify_them():
    def q(theme, outcome, day="2026-11-22"):
        return {"source": "question", "header": theme, "theme": theme, "outcome": outcome, "day": day}
    quiet = _rec(None)
    assert tr.signals(tr.facts([quiet])) == []
    loud = _rec(
        None,
        reply_gaps={"status": {"n": 20, "s": 3000}, "asked": {"n": 5, "s": 300}},
        question_wait_s=[10, 20, 4000],
        gh_repeat_reads={"n": 30, "s": 90},
        commands={"gh auth status": {"calls": 10, "s": 400, "pure_calls": 10, "pure_s": 400}},
        owner_decisions=[q("token and secret rotation", "followed", f"2026-11-{d}") for d in (15, 16, 17, 18, 21)]
        + [q("fix now or later", "overridden", "2026-11-22") for _ in range(30)],
        time={"wall_s": 0, "buckets": {"think_reply": 1000, "wait_machine": 600}},
    )
    got = {s["id"] for s in tr.signals(tr.facts([loud]))}
    assert got == {"stops-without-asking", "repeated-question", "open-questions-inflate-wait", "gh-polling",
                   "gh-slow-call", "question-surge", "background-waits"}


def test_facts_cap_open_questions_and_name_repeated_themes():
    rec = _rec(None, question_wait_s=[30, 60, 3000],
               owner_decisions=[{"source": "question", "header": "Token", "theme": "token and secret rotation",
                                 "outcome": "followed", "day": "2026-11-21"}] * 2)
    f = tr.facts([rec])
    w = f["waiting"]["question"]
    assert (w["n"], w["total_s"], w["long_n"], w["long_s"], w["capped_s"]) == (3, 3090, 1, 3000, 30 + 60 + 1800)
    assert f["decisions"]["themes"]["token and secret rotation"]["n"] == 2
    assert f["decisions"]["repeated_headers"] == [["token", 2]]


def test_the_html_report_has_the_new_sections(tmp_path):
    rec = _rec(None, reply_gaps={"status": {"n": 2, "s": 120}}, question_wait_s=[10],
               commands={"gh": {"calls": 2, "s": 6, "pure_calls": 2, "pure_s": 6},
                         "gh pr view": {"calls": 2, "s": 6, "pure_calls": 2, "pure_s": 6}},
               time={"wall_s": 100, "buckets": {"think_reply": 100}})
    page = tr.render_html([rec])
    for needle in ("Waiting on you, taken apart", "Repeated questions", "Commands: own time and chained time", "gh pr view"):
        assert needle in page


def test_a_command_with_a_pipe_or_chain_is_never_an_own_call(tmp_path):
    s = read(tmp_path, [
        prompt(0, "go"),
        asst(5, "a", "tool_use", [bash("git status --short && gh auth status")]), result(36, "a-0"),
        asst(40, "b", "end_turn"),
    ])
    c = s["commands"]
    assert c["gh"]["pure_calls"] == 0
    assert c["gh auth status"]["pure_calls"] == 0


def test_the_slow_gh_signal_ignores_calls_chained_with_other_commands():
    chained = {"gh auth status": {"calls": 10, "s": 400.0, "pure_calls": 0, "pure_s": 0.0}}
    own = {"gh auth status": {"calls": 10, "s": 400.0, "pure_calls": 10, "pure_s": 400.0}}
    base = _rec(None, commands=chained)
    assert [s for s in tr.signals(tr.facts([base])) if s["id"] == "gh-slow-call"] == []
    base = _rec(None, commands=own)
    assert [s["command"] for s in tr.signals(tr.facts([base])) if s["id"] == "gh-slow-call"] == ["gh auth status"]


def test_the_facts_command_writes_facts_and_signals_for_a_folder(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_rec(None, reply_gaps={"status": {"n": 20, "s": 3000},
                                                                        "asked": {"n": 5, "s": 300}})))
    out = tmp_path / "facts.json"
    assert tr.main(["facts", str(tmp_path), "--out", str(out)]) == 0
    bundle = json.loads(out.read_text())
    assert set(bundle) == {"facts", "signals", "records"}
    assert bundle["records"] == 1
    assert [s["id"] for s in bundle["signals"]] == ["stops-without-asking"]
    assert "waiting" in bundle["facts"]


def test_the_records_folder_is_not_read_back_into_itself(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_rec(None)))
    (tmp_path / "facts.json").write_text(json.dumps({"facts": {}, "signals": [], "records": 0}))
    assert len(tr.load_records(tmp_path)) == 1


def test_a_final_message_that_lists_what_waits_on_the_owner_is_blocked_not_status():
    k = tr.gap_kind
    assert k("- **C9, B7, D12:** waiting on your answers, as before.") == "blocked"
    assert k("Item 16 (the auto-merge call) needs your decision.") == "blocked"
    assert k("Committing needs the trailer, and pushing needs your go-ahead.") == "blocked"
    assert k("Pick option 1, 2 or 3 and I will continue.") == "blocked"
    assert k("Item 34 is still unticked. Nothing is committed.") == "status"
    assert k("Which option do you want?") == "asked"


def test_an_output_filter_or_a_status_echo_does_not_make_a_command_a_chain(tmp_path):
    s = read(tmp_path, [
        prompt(0, "go"),
        asst(5, "a", "tool_use", [bash("gh pr view 5 2>&1 | head -20")]), result(8, "a-0"),
        asst(10, "b", "tool_use", [bash("git commit -q -m x; echo \"exit=$?\"")]), result(14, "b-0"),
        asst(20, "c", "tool_use", [bash("git commit -q -m x && git log --oneline -1 | cat")]), result(23, "c-0"),
        asst(30, "d", "tool_use", [bash("gh pr view 5 && uv run pytest")]), result(90, "d-0"),
        asst(95, "e", "end_turn"),
    ])
    c = s["commands"]
    assert c["gh pr view"]["pure_calls"] == 1
    assert c["git commit"]["pure_calls"] == 2
    assert c["git commit"]["calls"] == 2
    assert c["gh"]["pure_calls"] == 1


def test_setup_steps_and_log_lines_around_a_command_do_not_make_it_a_chain(tmp_path):
    s = read(tmp_path, [
        prompt(0, "go"),
        asst(5, "a", "tool_use", [bash("cd /w/x && git add -A && git commit -q -m x && git log --oneline -1 && git status -sb")]),
        result(9, "a-0"),
        asst(15, "b", "tool_use", [bash("export A=1; git add f && git commit -q -m y && git push -u origin HEAD")]),
        result(25, "b-0"),
        asst(30, "c", "tool_use", [bash("git add f && git commit -q -m y && uv run pytest -q")]), result(90, "c-0"),
        asst(95, "d", "end_turn"),
    ])
    c = s["commands"]
    assert c["git commit"]["pure_calls"] == 1
    assert c["git commit"]["calls"] == 3
    assert c["git push"]["pure_calls"] == 0
