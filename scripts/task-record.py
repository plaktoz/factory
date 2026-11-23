"""Record what one task cost, then read the records later. Run from the repo root:

    python3 -I scripts/task-record.py write [--base origin/main]
    python3 -I scripts/task-record.py report [docs/retro] [--html PATH]

`write` makes docs/retro/<branch>.json from the Claude Code transcripts of the sessions that worked on this branch,
and from git. Each branch owns its file, and no other branch writes it, so merges cannot conflict. `report` totals a
folder: where active time goes, agent decisions by importance, your answers by outcome, tokens and friction.

Time comes from a walk over each transcript. Every second between its first and last event goes to one bucket: a
tool's run (by what the tool did), a wait on you (a question, or a permission the config did not allow), a wait on
background work, a reply gap under 30 minutes, time away (a gap of 30 minutes or more), or the agent thinking.
Tokens count once per message id, under the activity of that message. Cache reads are reported apart, because they
are context the model re-reads each turn rather than new work.
"""
import argparse
import html
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

RETRO = "docs/retro"
AWAY_S = 30 * 60
SLOW_S = 120
TOKEN_KEYS = {"input": "input_tokens", "output": "output_tokens",
              "cache_creation": "cache_creation_input_tokens", "cache_read": "cache_read_input_tokens"}
KINDS = ("product", "spec", "process")

GROUPS = {
    "agent development": {"agent_think", "think_reply", "build_product", "write_spec", "investigate", "delegate",
                          "run_tests"},
    "process and records": {"edit_records", "write_adr", "records_checks", "decision_pages", "github"},
    "git hooks": {"commit_hooks", "push_hooks"},
    "waiting on you": {"wait_reply", "wait_question", "wait_permission", "ask_owner"},
    "waiting on machine": {"wait_machine"},
}
AWAY = "away"
LABELS = {
    "agent_think": "agent thinking", "think_reply": "agent replies", "build_product": "building product",
    "write_spec": "writing specs and docs", "investigate": "reading and searching", "delegate": "subagents",
    "run_tests": "running tests", "edit_records": "editing records (tasks, decisions, AGENTS)",
    "write_adr": "writing ADRs", "records_checks": "records and docs checks", "decision_pages": "decision pages",
    "github": "GitHub calls", "commit_hooks": "git commit (company hooks)", "push_hooks": "git push (company hooks)",
    "ask_owner": "asking you", "wait_reply": "waiting for your reply",
    "wait_question": "waiting on your answer", "wait_permission": "waiting on a permission you decided",
    "wait_machine": "waiting on background work", AWAY: "away (not counted)",
}
# Most overhead first. A message takes the first activity in this list that any of its tools has.
OVERHEAD = ["commit_hooks", "push_hooks", "records_checks", "decision_pages", "edit_records", "write_adr", "github",
            "ask_owner", "write_spec", "build_product", "run_tests", "wait_machine", "delegate", "investigate"]
BASH_RULES = [
    ("commit_hooks", r"\bgit\b[^|;&]*\bcommit\b"),
    ("push_hooks", r"\bgit\b[^|;&]*\bpush\b"),
    ("records_checks", r"docs-check|records\.py|spec-pilot"),
    ("github", r"\bgh\b"),
    ("run_tests", r"pytest|\bnpm test\b|\bvitest\b"),
    ("wait_machine", r"(^|[;&|]\s*)sleep\s"),
]
SKILL_ACTIVITY = {"decision-page": "decision_pages", "revise-spec": "records_checks"}
EDIT_RECORDS = {"docs/decisions.md", "docs/tasks.md", "docs/tasks-archive.md", "docs/approvals.md", "docs/process.md",
                "docs/README.md", "AGENTS.md"}
MARKERS = ("/factory/", "/docs/", "/scripts/", "/.github/")

REOPEN = re.compile(r"\breopen|\bDecisions? row|\bD\d+\b")
COSTLY = re.compile(r"rotat|secret|token|credential|delete|publish|public|deploy|migrat|data format|schema|"
                    r"dependenc|irreversib|force", re.I)
SCOPE = re.compile(r"\bscope\b|\bphase\b|\bdefer|\bdrop\b|\bpostpone", re.I)
OPEN_CHOICE = re.compile(r"\bor\b|either|trade-?off|which is better|no clear", re.I)
CATEGORIES = [
    ("security and ops", re.compile(r"token|secret|credential|rotat|gateway|sandbox|permission|\bauth", re.I)),
    ("process and records", re.compile(r"tasks?\.md|\blog\b|\badr\b|record|decision page|\bPRs?\b|pull request|merge|"
                                       r"issue|process|approval|commit", re.I)),
    ("spec and design", re.compile(r"spec|scorecard|module|contract|schema|design|criteri|section", re.I)),
    ("code", re.compile(r"test|language|engine|adapter|function|code|dependenc|worker|lint|hook|script|launcher|"
                        r"driver|\bcli\b", re.I)),
    ("scope and phase", re.compile(r"scope|phase|wave", re.I)),
]
HARNESS = ("<task-notification>", "<command-name>", "<command-message>", "<local-command")
DELIVER = re.compile(r"\b(push|pr|pull request|merge|commit)\b", re.I)
POLL = re.compile(r"\b(status|done|longer|taking|progress|how long|still|where are)\b", re.I)
APPROVE = re.compile(r"^\s*(yes|yeah|yep|y|ok|okay|continue|go|go ahead|proceed|sure|do it|approved?)\b", re.I)
STEER = re.compile(r"\b(incorrect|wrong|should|needs? to|instead|not what|why|don'?t|do not|stop|again|"
                   r"too (many|much))\b", re.I)
PAGE_CHOICE = re.compile(r"^\s*[-*]?\s*(D\d+)\s+([^:\n]+):\s*(.+?)\s*\[([a-z0-9-]+)\]\s*"
                         r"\((recommended|not the recommendation)\)", re.M)
PAGE_UNSURE = re.compile(r"^\s*[-*]?\s*(D\d+)\s+([^:\n]+):\s*NOT SURE", re.M)


# --- classification -----------------------------------------------------------------------------------------------

def classify(path):
    """Lines of code by kind. product: what ships in the kit. spec: the design. process: how this repo is run."""
    if path.startswith(RETRO + "/"):
        return None
    if path.startswith("factory/"):
        return "product"
    if path.startswith("docs/design/"):
        return "spec"
    return "process"


def repo_relative(path):
    """The path inside the repo, or None when the path is outside it (a memory file, a file in another project)."""
    p = path if path.startswith("/") else "/" + path
    if p.endswith("/AGENTS.md"):
        return "AGENTS.md"
    cut = max((p.rfind(m) for m in MARKERS), default=-1)
    return p[cut + 1:] if cut >= 0 else None


def file_activity(path):
    rel = repo_relative(path)
    if rel is None:
        return "investigate"
    if rel.startswith("docs/retro/") or rel in EDIT_RECORDS:
        return "edit_records"
    if rel.startswith("docs/adr/"):
        return "write_adr"
    if rel.startswith("docs/"):
        return "write_spec"
    return "build_product"


def tool_activity(name, inp):
    inp = inp or {}
    if name in ("Edit", "Write", "NotebookEdit"):
        return file_activity(inp.get("file_path") or inp.get("notebook_path") or "")
    if name == "Bash":
        cmd = inp.get("command") or ""
        return next((act for act, rx in BASH_RULES if re.search(rx, cmd)), "investigate")
    if name == "Skill":
        return SKILL_ACTIVITY.get(inp.get("skill") or "", "investigate")
    if name == "AskUserQuestion":
        return "ask_owner"
    if name in ("Agent", "SendMessage", "ListAgents", "TaskStop"):
        return "delegate"
    if name in ("Monitor", "ScheduleWakeup"):
        return "wait_machine"
    return "investigate"


def message_activity(tools):
    used = {tool_activity(name, inp) for name, inp in tools}
    return next((act for act in OVERHEAD if act in used), "think_reply")


def classify_decision(text):
    """Category, importance and the stop trigger a decision would meet, read from its question text."""
    if REOPEN.search(text):
        trigger, importance = "reopens-decision", "high"
    elif COSTLY.search(text):
        trigger, importance = "costly-to-reverse", "high"
    elif SCOPE.search(text):
        trigger, importance = "changes-scope", "medium"
    elif OPEN_CHOICE.search(text):
        trigger, importance = "no-clear-winner", "medium"
    else:
        trigger, importance = "routine", "low"
    category = next((name for name, rx in CATEGORIES if rx.search(text)), "other")
    return {"category": category, "importance": importance, "trigger": trigger}


def classify_prompt(text):
    t = text.strip()
    if t.startswith("[Request interrupted"):
        return "interrupt"
    if t.startswith(HARNESS):
        return "harness"
    if t.startswith("Task:") or "<pasted_content" in t or len(t) > 400:
        return "handoff"
    if len(t) < 200 and DELIVER.search(t):
        return "deliver"
    if len(t) < 150 and POLL.search(t):
        return "poll"
    if len(t) < 60 and APPROVE.search(t):
        return "approve"
    if STEER.search(t):
        return "steer"
    return "instruction"


def group_of(key):
    return next((g for g, acts in GROUPS.items() if key in acts), None)


# --- transcripts --------------------------------------------------------------------------------------------------

def _ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def _load(path):
    return [json.loads(raw) for raw in Path(path).read_text(encoding="utf-8").splitlines() if raw.strip()]


def _events(entries):
    for e in entries:
        if e.get("isSidechain") or e.get("isMeta") or not e.get("timestamp"):
            continue
        if e.get("type") in ("assistant", "user"):
            yield e


def _text(message):
    c = message.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _result_text(block):
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(x.get("text", "") for x in c if isinstance(x, dict))
    return ""


def _messages(entries):
    """One entry per assistant message id: its usage and its tool uses. A message is logged once per content block."""
    msgs = {}
    for e in entries:
        if e.get("type") != "assistant":
            continue
        m = e.get("message") or {}
        mid = m.get("id")
        if not mid:
            continue
        slot = msgs.setdefault(mid, {"usage": m.get("usage") or {}, "tools": {}})
        for b in m.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                slot["tools"].setdefault(b["id"], (b["name"], b.get("input") or {}))
    return msgs


def _sum_usage(msgs):
    total = dict.fromkeys(TOKEN_KEYS, 0)
    for m in msgs:
        for k, field in TOKEN_KEYS.items():
            total[k] += m["usage"].get(field) or 0
    return total


def _by_activity(msgs):
    table = {}
    for m in msgs:
        u = m["usage"]
        slot = table.setdefault(message_activity(list(m["tools"].values())), {"new": 0, "reread": 0})
        slot["new"] += (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) \
            + (u.get("output_tokens") or 0)
        slot["reread"] += u.get("cache_read_input_tokens") or 0
    return table


def _tool_bucket(entry, tid, open_tools):
    _, name, inp = open_tools[tid]
    source = (entry.get("permissionDecision") or {}).get("source")
    if name == "AskUserQuestion":
        return "wait_question"
    if source and source != "config":
        return "wait_permission"
    return tool_activity(name, inp)


def _outcome(options, answer):
    for o in options:
        if o.get("label") == answer:
            return "followed" if "(Recommended)" in o["label"] else "overridden"
    return "custom"


def _question_record(q, answer):
    rec = {"source": "question", "header": q.get("header") or q.get("question", ""),
           "question": q.get("question", ""),
           "outcome": "unanswered" if answer is None else _outcome(q.get("options") or [], answer),
           "answer": str(answer or "")[:120]}
    rec.update(classify_decision(q.get("question", "")))
    return rec


def _page_answers(text):
    """Answers on a decision page, as the page's prompt writes them: one line per card, in the owner's words."""
    out = []
    for m in PAGE_CHOICE.finditer(text):
        rec = {"source": "page", "id": m[1], "header": m[2].strip(), "answer": m[3].strip(),
               "outcome": "followed" if m[5] == "recommended" else "overridden"}
        rec.update(classify_decision(rec["header"] + " " + rec["answer"]))
        out.append(rec)
    for m in PAGE_UNSURE.finditer(text):
        rec = {"source": "page", "id": m[1], "header": m[2].strip(), "outcome": "unsure"}
        rec.update(classify_decision(rec["header"]))
        out.append(rec)
    return out


def _add_owner(owner, seen, rec):
    key = (rec["source"], rec.get("id") or rec["header"])
    if key not in seen:
        seen.add(key)
        owner.append(rec)


def read_session(path, subagent_paths):
    """Time, tokens, prompts, owner answers and friction of one session. Subagent tokens are counted apart."""
    entries = _load(path)
    buckets = defaultdict(float)
    prompts = Counter()
    owner, seen_owner = [], set()
    friction = {"tool_errors": 0, "interrupts": 0, "secret_scans": 0, "slow": []}
    state, cursor, first, last = "start", None, None, None
    open_tools, asked, seen_ids = {}, {}, set()

    for e in _events(entries):
        t = _ts(e["timestamp"])
        m = e.get("message") or {}
        blocks = m.get("content") if isinstance(m.get("content"), list) else []
        results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
        text = "" if results else _text(m)
        prompt = e["type"] == "user" and not results and text.strip() != ""
        kind = classify_prompt(text) if prompt else None
        if cursor is None:
            cursor = first = t

        # The interval since the last event goes to the bucket the state says it was spent on.
        closing = next((b for b in results if b.get("tool_use_id") in open_tools), None)
        if state == "tool" and open_tools:
            tid = closing["tool_use_id"] if closing else next(iter(open_tools))
            bucket = _tool_bucket(e, tid, open_tools)
        elif state == "end" and prompt:
            if kind == "harness":
                bucket = "wait_machine"
            else:
                bucket = AWAY if t - cursor > AWAY_S else "wait_reply"
        elif e["type"] == "assistant":
            # Time before a message is the model writing it, so it goes to what that message does.
            tools = [(b["name"], b.get("input") or {}) for b in blocks
                     if isinstance(b, dict) and b.get("type") == "tool_use"]
            bucket = message_activity(tools)
        else:
            bucket = "agent_think"
        buckets[bucket] += t - cursor
        cursor = last = t

        if e["type"] == "assistant":
            # A message is logged as several entries that share its id, so each tool use opens its own span
            # wherever it arrives. Re-logged content is skipped by tool id.
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id") not in seen_ids:
                    seen_ids.add(b["id"])
                    open_tools[b["id"]] = (t, b["name"], b.get("input") or {})
                    if b["name"] == "AskUserQuestion":
                        asked[b["id"]] = (b.get("input") or {}).get("questions", [])
            state = "tool" if open_tools else ("end" if m.get("stop_reason") == "end_turn" else "think")
        elif results:
            tur = e.get("toolUseResult") if isinstance(e.get("toolUseResult"), dict) else {}
            for b in results:
                if b.get("is_error"):
                    friction["tool_errors"] += 1
                if "Block Secrets" in _result_text(b):
                    friction["secret_scans"] += 1
                tid = b.get("tool_use_id")
                if tid not in open_tools:
                    continue
                t0, name, inp = open_tools.pop(tid)
                if t - t0 > SLOW_S:
                    label = (inp.get("command") or "")[:60] if name == "Bash" else name
                    friction["slow"].append([round(t - t0), label])
                if name == "AskUserQuestion":
                    answers = tur.get("answers") or {}
                    for q in asked.get(tid, []):
                        _add_owner(owner, seen_owner, _question_record(q, answers.get(q.get("question"))))
            state = "tool" if open_tools else "think"
        elif prompt:
            prompts[kind] += 1
            if kind == "interrupt":
                friction["interrupts"] += 1
            for rec in _page_answers(text):
                _add_owner(owner, seen_owner, rec)
            open_tools.clear()
            state = "think"

    main = list(_messages(entries).values())
    subs = [m for p in subagent_paths for m in _messages(_load(p)).values()]
    hooks = defaultdict(float)
    for e in entries:
        a = e.get("attachment") or {}
        if e.get("type") == "attachment" and a.get("type") == "hook_success" and a.get("hookEvent"):
            hooks[a["hookEvent"]] += float(a.get("durationMs") or 0) / 1000
    return {
        "time": {"wall_s": round(last - first, 1) if first is not None else 0.0,
                 "buckets": {k: round(v, 1) for k, v in buckets.items() if v}},
        "tokens": {"main": _sum_usage(main), "subagent": _sum_usage(subs), "by_activity": _by_activity(main + subs)},
        "prompts": dict(prompts),
        "owner_decisions": owner,
        "friction": friction,
        "hooks": {k: round(v, 1) for k, v in hooks.items()},
    }


# --- git ------------------------------------------------------------------------------------------------------------

def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def _importance(files):
    if any(f.startswith(("docs/design/", "docs/adr/")) for f in files):
        return "high"
    if files and all(f == "docs/decisions.md" for f in files):
        return "low"
    return "medium"


def _category(files):
    first = files[0] if files else ""
    if first.startswith(("docs/design/", "docs/adr/")):
        return "spec and design"
    if first == "docs/decisions.md":
        return "reversible choice"
    if first.startswith(("factory/", "scripts/")):
        return "code"
    return "process and records"


def read_git(repo, base):
    """Commits, the decisions they record (Decision trailers) and lines changed since they left `base`."""
    log = _git(repo, "log", f"{base}..HEAD", "--no-merges", "--format=%H%x1f%B%x1e")
    commits = [c.split("\x1f", 1) for c in log.split("\x1e") if "\x1f" in c]
    decisions = []
    for sha, body in commits:
        ids = re.findall(r"^Decision: (\S+)", body, re.M)
        if not ids:
            continue
        files = _git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha.strip()).split()
        for i in ids:
            decisions.append({"id": i, "importance": _importance(files), "category": _category(files),
                              "commit": sha.strip()[:9]})
    lines = dict.fromkeys(KINDS, 0)
    for row in _git(repo, "diff", "--numstat", f"{base}...HEAD").splitlines():
        added, _, path = row.split("\t", 2)
        kind = classify(path)
        if kind and added != "-":
            lines[kind] += int(added)
    names = _git(repo, "diff", "--name-status", f"{base}...HEAD").splitlines()
    bodies = [b for _, b in commits]
    return {
        "commits": len(commits),
        "decision_trailers": len(decisions),
        "agent_decisions": decisions,
        "adrs_added": sum(1 for r in names if re.match(r"A\tdocs/adr/\d{4}-.*\.md$", r)),
        "lines": lines,
        "agent_runs": sorted({r for b in bodies for r in re.findall(r"^Agent-Run: (\S+)", b, re.M)}),
    }


def _project_dir(root, sessions_root):
    return sessions_root / re.sub(r"[/.]", "-", str(root))


def find_sessions(root, branch, agent_runs, sessions_root):
    """Transcripts for this branch: this worktree's sessions on it, and any session an Agent-Run trailer names."""
    found = {}
    for p in _project_dir(root, sessions_root).glob("*.jsonl"):
        for raw in p.read_text(encoding="utf-8").splitlines():
            if f'"gitBranch": "{branch}"' in raw or f'"gitBranch":"{branch}"' in raw:
                found[p.stem] = p
                break
    for run in agent_runs:
        for p in sessions_root.glob(f"*/{run}.jsonl"):
            found[run] = p
    return found


def _add_into(total, more):
    for k, v in more.items():
        total[k] = total.get(k, 0) + v


def build_record(root, base, sessions_root):
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    g = read_git(root, base)
    sessions = find_sessions(root, branch, g["agent_runs"], sessions_root)
    parts = [read_session(p, sorted((p.parent / sid / "subagents").glob("agent-*.jsonl")))
             for sid, p in sessions.items()]
    buckets, prompts, hooks = defaultdict(float), Counter(), defaultdict(float)
    tokens = {"main": {}, "subagent": {}, "by_activity": {}}
    friction = {"tool_errors": 0, "interrupts": 0, "secret_scans": 0, "slow": []}
    owner, seen = [], set()
    wall = 0.0
    for s in parts:
        wall += s["time"]["wall_s"]
        for k, v in s["time"]["buckets"].items():
            buckets[k] += v
        prompts.update(s["prompts"])
        for k, v in s["hooks"].items():
            hooks[k] += v
        _add_into(tokens["main"], s["tokens"]["main"])
        _add_into(tokens["subagent"], s["tokens"]["subagent"])
        for act, v in s["tokens"]["by_activity"].items():
            _add_into(tokens["by_activity"].setdefault(act, {}), v)
        for rec in s["owner_decisions"]:
            _add_owner(owner, seen, rec)
        for k in ("tool_errors", "interrupts", "secret_scans"):
            friction[k] += s["friction"][k]
        friction["slow"] += s["friction"]["slow"]
    return {
        "task": branch.split("/")[-1], "branch": branch, "base": base, "sessions": sorted(sessions),
        "commits": g["commits"], "lines": g["lines"], "adrs_added": g["adrs_added"], "agent_runs": g["agent_runs"],
        "time": {"wall_s": round(wall, 1), "buckets": {k: round(v, 1) for k, v in buckets.items() if v}},
        "tokens": tokens,
        "prompts": dict(prompts),
        "owner_decisions": owner,
        "agent_decisions": g["agent_decisions"],
        "friction": friction,
        "hooks": {k: round(v, 1) for k, v in hooks.items()},
    }


# --- reports --------------------------------------------------------------------------------------------------------

def load_records(folder):
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(folder).glob("*.json"))]


def merge_records(records):
    buckets, by_act, hooks = Counter(), {}, Counter()
    friction = {"tool_errors": 0, "interrupts": 0, "secret_scans": 0, "slow": []}
    agent, owner = [], []
    for r in records:
        buckets.update(r["time"]["buckets"])
        for act, v in r["tokens"]["by_activity"].items():
            _add_into(by_act.setdefault(act, {}), v)
        hooks.update(r["hooks"])
        for k in ("tool_errors", "interrupts", "secret_scans"):
            friction[k] += r["friction"][k]
        friction["slow"] += r["friction"]["slow"]
        agent += r["agent_decisions"]
        owner += r["owner_decisions"]
    return {"time": {"buckets": dict(buckets)}, "tokens": {"by_activity": by_act}, "hooks": dict(hooks),
            "friction": friction, "agent_decisions": agent, "owner_decisions": owner}


def group_shares(rec):
    b = rec["time"]["buckets"]
    active = sum(v for k, v in b.items() if k != AWAY)
    shares = dict.fromkeys(GROUPS, 0.0)
    for k, v in b.items():
        g = group_of(k)
        if g and k != AWAY:
            shares[g] += v
    return active, {g: (100 * v / active if active else 0.0) for g, v in shares.items()}


def summarize(rec):
    active, pct = group_shares(rec)
    new, reread = Counter(), Counter()
    for act, v in rec["tokens"]["by_activity"].items():
        g = group_of(act) or "other"
        new[g] += v["new"]
        reread[g] += v["reread"]
    new_total, reread_total = sum(new.values()) or 1, sum(reread.values()) or 1
    out = Counter(d["outcome"] for d in rec["owner_decisions"])
    answered = out["followed"] + out["overridden"] + out["custom"]
    return {
        "active": active, "pct": pct,
        "new": sum(new.values()), "reread": sum(reread.values()),
        "new_pct": {g: 100 * v / new_total for g, v in new.items()},
        "reread_pct": {g: 100 * v / reread_total for g, v in reread.items()},
        "imp": Counter(d["importance"] for d in rec["agent_decisions"]),
        "out": out,
        "not_recommended_rate": (100 * (out["overridden"] + out["custom"]) / answered) if answered else None,
        "friction": rec["friction"], "hooks": rec["hooks"],
    }


def ranked_non_dev(records):
    b = merge_records(records)["time"]["buckets"]
    active = sum(v for k, v in b.items() if k != AWAY)
    rows = sorted(((k, v) for k, v in b.items() if k != AWAY and group_of(k) != "agent development"),
                  key=lambda kv: -kv[1])
    return [(LABELS.get(k, k), _hm(v), 100 * v / active if active else 0.0) for k, v in rows]


def _hm(seconds):
    m = round(seconds / 60)
    return f"{m // 60}h{m % 60:02d}m"


def _rows(records):
    rows = [(r["task"], summarize(r)) for r in records]
    if records:
        rows.append(("TOTAL", summarize(merge_records(records))))
    return rows


def render_text(records):
    if not records:
        return "no task records"
    head = ["task", "active", *GROUPS, "agent H/M/L", "answers", "not rec.", "new tok", "reread tok"]
    table = [head]
    for name, s in _rows(records):
        table.append([name, _hm(s["active"]), *[f"{s['pct'][g]:.0f}%" for g in GROUPS],
                      f"{s['imp']['high']}/{s['imp']['medium']}/{s['imp']['low']}",
                      str(s["out"]["followed"] + s["out"]["overridden"] + s["out"]["custom"]),
                      "-" if s["not_recommended_rate"] is None else f"{s['not_recommended_rate']:.0f}%",
                      f"{s['new'] / 1000:.0f}k", f"{s['reread'] / 1e6:.1f}M"])
    w = [max(len(r[i]) for r in table) for i in range(len(head))]
    fmt = lambda r: "  ".join(c.ljust(w[i]) for i, c in enumerate(r))
    lines = [fmt(table[0]), *map(fmt, table[1:]), "", "Non-development time, ranked (share of active time):"]
    lines += [f"  {label:<40} {hm:>8} {p:5.1f}%" for label, hm, p in ranked_non_dev(records)]
    lines += ["", "Percentages are of active time, which leaves out time away.",
              "new tok = input + cache writes + output. reread tok = cache reads, context the model re-reads each turn."]
    return "\n".join(lines)


HTML_HEAD = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Task cost</title>
<style>
:root{--ink:#1d2430;--muted:#5b6678;--line:#d9dee7;--bar:#2f6fb3;--bg:#fff}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--ink:#e6eaf0;--muted:#9aa4b5;--line:#2c3441;--bar:#6aa3e0;--bg:#14181f}}
:root[data-theme="dark"]{--ink:#e6eaf0;--muted:#9aa4b5;--line:#2c3441;--bar:#6aa3e0;--bg:#14181f}
body{background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif;margin:16px;max-width:1100px}
h2{font-size:17px;margin:28px 0 6px}
p.note{color:var(--muted);margin:4px 0}
table{border-collapse:collapse;width:100%;margin:4px 0}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:600;color:var(--muted)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.track{height:6px;background:var(--line);border-radius:3px;margin-top:4px;min-width:80px}
.bar{height:6px;background:var(--bar);border-radius:3px}
tr.total td{font-weight:600}
</style><body>
"""


def _track(pct):
    return f'<div class="track"><div class="bar" style="width:{min(max(pct, 0), 100):.1f}%"></div></div>'


def render_html(records):
    e = html.escape
    if not records:
        return HTML_HEAD + "<p>No task records.</p></body></html>\n"
    rows = _rows(records)
    groups = list(GROUPS)
    out = [HTML_HEAD, "<h1 style='font-size:22px;margin:0 0 4px'>Task cost</h1>",
           f"<p class=note>{len(records)} task record(s). Percentages are of active time, which leaves out time away.</p>",
           "<h2>Where active time goes</h2><table><tr><th>Task</th><th class=num>Active</th>"
           + "".join(f"<th>{e(g)}</th>" for g in groups) + "</tr>"]
    for name, s in rows:
        cls = " class=total" if name == "TOTAL" else ""
        cells = "".join(f"<td class=num>{s['pct'][g]:.0f}%{_track(s['pct'][g])}</td>" for g in groups)
        out.append(f"<tr{cls}><td>{e(name)}</td><td class=num>{_hm(s['active'])}</td>{cells}</tr>")
    out.append("</table>")

    out.append("<h2>Non-development time, ranked</h2><table><tr><th>Activity</th><th class=num>Time</th>"
               "<th class=num>Share of active</th></tr>")
    for label, hm, p in ranked_non_dev(records):
        out.append(f"<tr><td>{e(label)}</td><td class=num>{hm}</td><td class=num>{p:.1f}%{_track(p)}</td></tr>")
    out.append("</table>")

    out.append("<h2>Decisions</h2><p class=note>Agent decisions are recorded in commits (importance by where they "
               "land). Your answers are read from the transcripts. &quot;Not recommended&quot; counts an answer that "
               "picked another option or wrote its own.</p>"
               "<table><tr><th>Task</th><th class=num>Agent high</th><th class=num>medium</th><th class=num>low</th>"
               "<th class=num>Your answers</th><th class=num>Followed</th><th class=num>Not recommended</th>"
               "<th class=num>Unsure</th></tr>")
    for name, s in rows:
        o = s["out"]
        rate = "-" if s["not_recommended_rate"] is None else f"{s['not_recommended_rate']:.0f}%"
        cls = " class=total" if name == "TOTAL" else ""
        out.append(f"<tr{cls}><td>{e(name)}</td><td class=num>{s['imp']['high']}</td><td class=num>"
                   f"{s['imp']['medium']}</td><td class=num>{s['imp']['low']}</td>"
                   f"<td class=num>{o['followed'] + o['overridden'] + o['custom']}</td>"
                   f"<td class=num>{o['followed']}</td><td class=num>{o['overridden'] + o['custom']} ({rate})</td>"
                   f"<td class=num>{o['unsure']}</td></tr>")
    out.append("</table>")

    out.append("<h2>Tokens</h2><p class=note>New tokens are input, cache writes and output: work the model did. "
               "Reread tokens are cache reads: context sent again on each turn.</p>"
               "<table><tr><th>Task</th><th class=num>New</th><th class=num>Reread</th>"
               + "".join(f"<th>{e(g)} (new)</th>" for g in groups) + "</tr>")
    for name, s in rows:
        cls = " class=total" if name == "TOTAL" else ""
        cells = "".join(f"<td class=num>{s['new_pct'].get(g, 0):.0f}%</td>" for g in groups)
        out.append(f"<tr{cls}><td>{e(name)}</td><td class=num>{s['new'] / 1000:.0f}k</td>"
                   f"<td class=num>{s['reread'] / 1e6:.1f}M</td>{cells}</tr>")
    out.append("</table>")

    out.append("<h2>Friction</h2><table><tr><th>Task</th><th class=num>Tool errors</th><th class=num>Interrupts</th>"
               "<th class=num>Secret scans</th><th class=num>Commands over 2 min</th><th>Hook time</th></tr>")
    for name, s in rows:
        f = s["friction"]
        hooks = ", ".join(f"{e(k)} {v}s" for k, v in sorted(s["hooks"].items())) or "-"
        cls = " class=total" if name == "TOTAL" else ""
        out.append(f"<tr{cls}><td>{e(name)}</td><td class=num>{f['tool_errors']}</td>"
                   f"<td class=num>{f['interrupts']}</td><td class=num>{f['secret_scans']}</td>"
                   f"<td class=num>{len(f['slow'])}</td><td>{hooks}</td></tr>")
    out.append("</table></body></html>\n")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write")
    w.add_argument("--base", default="origin/main")
    w.add_argument("--sessions-root", type=Path, default=Path.home() / ".claude/projects")
    r = sub.add_parser("report")
    r.add_argument("folder", nargs="?", default=RETRO)
    r.add_argument("--html", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "report":
        records = load_records(a.folder)
        if a.html:
            a.html.write_text(render_html(records), encoding="utf-8")
            print(f"wrote {a.html}")
        else:
            print(render_text(records))
        return 0
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    rec = build_record(root, a.base, a.sessions_root)
    out = root / RETRO / f"{rec['branch'].replace('/', '-')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
