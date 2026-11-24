"""Record what one task cost, then read the records later. Run from the repo root:

    python3 -I scripts/task-record.py write [--base origin/main]
    python3 -I scripts/task-record.py report [docs/retro] [--html PATH]
    python3 -I scripts/task-record.py facts [docs/retro] --out PATH

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
    "chained shell (unsplit)": {"deliver_chain", "mixed_shell"},
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
    "deliver_chain": "commit + push + gh in one command", "mixed_shell": "tests or checks chained with git",
    "ask_owner": "asking you", "wait_reply": "waiting for your reply",
    "wait_question": "waiting on your answer", "wait_permission": "waiting on a permission you decided",
    "wait_machine": "waiting on background work", AWAY: "away (not counted)",
}
# Most overhead first. A message takes the first activity in this list that any of its tools has.
OVERHEAD = ["deliver_chain", "mixed_shell", "commit_hooks", "push_hooks", "records_checks", "decision_pages", "edit_records", "write_adr", "github",
            "ask_owner", "write_spec", "build_product", "run_tests", "wait_machine", "delegate", "investigate"]
CMD_CATS = [
    ("git commit", r"\bgit\b[^|;&]*\bcommit\b"),
    ("git push", r"\bgit\b[^|;&]*\bpush\b"),
    ("gh", r"\bgh\b"),
    ("pytest", r"pytest|\bnpm test\b|\bvitest\b"),
    ("records", r"docs-check|records\.py|spec-pilot"),
    ("sleep", r"(^|[;&|]\s*)sleep\s"),
]
CAT_ACTIVITY = {"git commit": "commit_hooks", "git push": "push_hooks", "gh": "github", "pytest": "run_tests",
                "records": "records_checks", "sleep": "wait_machine"}
DELIVERY = {"git commit", "git push", "gh"}
GH_SUB = re.compile(r"\bgh\s+(api|pr|issue|run|repo|auth|workflow|release|search|label|gist)\b(?:\s+([a-z][a-z-]*))?")
GH_READ = re.compile(r"\bgh\s+(pr|issue)\s+(view|checks|list|status)\b(?:\s+#?(\d+))?")
REPEAT_READ_S = 600
LONG_WAIT_S = 1800
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


def _code(cmd):
    """The command without heredoc bodies and quoted text, so a commit message cannot name a command it runs."""
    cmd = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\s*\1\b", "", cmd, flags=re.S)
    return re.sub(r"'[^']*'|\"[^\"]*\"", "''", cmd)


def bash_categories(cmd):
    code = _code(cmd)
    return {name for name, rx in CMD_CATS if re.search(rx, code)}


def tool_activity(name, inp):
    inp = inp or {}
    if name in ("Edit", "Write", "NotebookEdit"):
        return file_activity(inp.get("file_path") or inp.get("notebook_path") or "")
    if name == "Bash":
        cats = bash_categories(inp.get("command") or "")
        if not cats:
            return "investigate"
        if len(cats) == 1:
            return CAT_ACTIVITY[next(iter(cats))]
        return "deliver_chain" if cats <= DELIVERY else "mixed_shell"
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


QUESTION_THEMES = [
    ("token and secret rotation", re.compile(r"(gateway|auth|api|access)[ _-]?token|\bsecrets?\b|credential|rotat", re.I)),
    ("push, PR and merge approval", re.compile(r"\bpush\b|\bmerge (it|this|that|the (branch|PR|pull request))\b|"
                                              r"\b(open|push|merge|close)\b[^.?]{0,20}\b(PR|pull request)\b", re.I)),
    ("fix now or later", re.compile(r"fix (it )?now|now or|\blater\b|follow-up|record (as|a)\b|defer|backfill", re.I)),
    ("where it lives", re.compile(r"\bwhere\b|which (file|folder|path|name)|rename|\bmove\b", re.I)),
    ("spec wording", re.compile(r"wording|\bspec\b|contract|section", re.I)),
]


def question_theme(text):
    return next((name for name, rx in QUESTION_THEMES if rx.search(text)), "other")


# A closing line that asks for a reply without a question mark: a command to answer, a request to paste back.
_ASKS_FOR_REPLY = re.compile(
    r"\breply with\b|\bsay \(?[a-c1-9]\)?[,) ]|\bpaste (?:the|that|it|this)\b[^.\n]{0,60}\bback\b|"
    r"\btell me (?:which|whether|what)\b|\b(?:once|until|when) you(?:'ve| have)? answer", re.I)


def gap_kind(text):
    """What the agent ended its turn with, read from its last message: a question, a delivery, a finish or a status."""
    t = text.strip()
    tail = t[-400:].lower()
    if t.endswith("?") or _ASKS_FOR_REPLY.search(tail) \
            or re.search(r"which (option|do you)|do you want|should i\b|let me know|your call|approve", tail):
        return "asked"
    if re.search(r"waiting on you|needs? your|your (go-ahead|decision|answer|call|approval)|pick (an )?option|"
                 r"option \d,? .*\bor\b|awaiting (your|the owner)", tail):
        return "blocked"
    if re.search(r"pull/\d+|\bpushed\b|\bopened\b", tail):
        return "delivered"
    if re.search(r"\bdone\b|complete|finished|passed", tail):
        return "finished"
    return "status"


_PIPE_FILTER = re.compile(r"^(head|tail|cat|tee|wc|sort|uniq|grep|cut|tr|sed|awk)\b")
_TRAILER = re.compile(r"^(echo|printf|true|pwd|git log|git status|git diff --stat|git branch --show-current)\b")
_SETUP = re.compile(r"^(cd|export|set|unset|source|git add|git checkout -q|git switch|env|mkdir|\w+=\S*)\b|^\w+=")


def _is_single(cmd):
    """One command. Setup before it (cd, export, git add), log lines after it, and output filters add no work."""
    code = _code(cmd).strip()
    steps = [p.strip() for p in re.split(r"&&|\|\||;|\n", code) if p.strip()]
    while len(steps) > 1 and _TRAILER.match(steps[-1]):
        steps.pop()
    while len(steps) > 1 and _SETUP.match(steps[0]):
        steps.pop(0)
    if len(steps) != 1:
        return False
    return all(_PIPE_FILTER.match(p.strip()) for p in steps[0].split("|")[1:])


def _count_command(commands, read_at, repeats, cmd, started, span):
    """Charge a shell command's time to each kind it contains, and apart to the kinds it is the only one of."""
    cats = bash_categories(cmd)
    pure = len(cats) == 1 and _is_single(cmd)
    keys = list(cats)
    if "gh" in cats:
        m = GH_SUB.search(_code(cmd))
        if m:
            keys.append(" ".join(["gh", m[1]] + ([m[2]] if m[2] else [])))
        r = GH_READ.search(_code(cmd))
        if r:
            ident = (r[1], r[3] or "list")
            if ident in read_at and started - read_at[ident] < REPEAT_READ_S:
                repeats["n"] += 1
                repeats["s"] += span
            read_at[ident] = started
    for k in keys:
        slot = commands[k]
        slot["calls"] += 1
        slot["s"] += span
        if pure:
            slot["pure_calls"] += 1
            slot["pure_s"] += span


def _question_record(q, answer, day=""):
    rec = {"source": "question", "header": q.get("header") or q.get("question", ""),
           "question": q.get("question", ""), "day": day,
           "theme": question_theme((q.get("header") or "") + " " + q.get("question", "")),
           "outcome": "unanswered" if answer is None else _outcome(q.get("options") or [], answer),
           "answer": str(answer or "")[:120]}
    rec.update(classify_decision(q.get("question", "")))
    return rec


def _page_answers(text, day=""):
    """Answers on a decision page, as the page's prompt writes them: one line per card, in the owner's words."""
    out = []
    for m in PAGE_CHOICE.finditer(text):
        rec = {"source": "page", "id": m[1], "header": m[2].strip(), "answer": m[3].strip(), "day": day,
               "outcome": "followed" if m[5] == "recommended" else "overridden"}
        rec["theme"] = question_theme(rec["header"] + " " + rec["answer"])
        rec.update(classify_decision(rec["header"] + " " + rec["answer"]))
        out.append(rec)
    for m in PAGE_UNSURE.finditer(text):
        rec = {"source": "page", "id": m[1], "header": m[2].strip(), "outcome": "unsure", "day": day}
        rec["theme"] = question_theme(rec["header"])
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
    commands = defaultdict(lambda: {"calls": 0, "s": 0.0, "pure_calls": 0, "pure_s": 0.0})
    notify = defaultdict(lambda: {"n": 0, "s": 0.0})
    worked_since_end, last_end_t = False, None
    reply_gaps = defaultdict(lambda: {"n": 0, "s": 0.0})
    question_wait_s, read_at, repeats = [], {}, {"n": 0, "s": 0.0}
    msg_text, end_text = defaultdict(str), ""

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
                if text.lstrip().startswith("<task-notification") and last_end_t is not None \
                        and not worked_since_end:
                    gap = t - last_end_t
                    for key in ("idle", "over_30min") if gap > AWAY_S else ("idle",):
                        notify[key]["n"] += 1
                        notify[key]["s"] += gap
            elif t - cursor > AWAY_S:
                bucket = AWAY
            else:
                bucket = "wait_reply"
                slot = reply_gaps[gap_kind(end_text)]
                slot["n"] += 1
                slot["s"] += t - cursor
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
            msg_text[m.get("id")] += _text(m)
            if m.get("stop_reason") == "end_turn":
                end_text = msg_text[m.get("id")]
                last_end_t, worked_since_end = t, False
            # A message is logged as several entries that share its id, so each tool use opens its own span
            # wherever it arrives. Re-logged content is skipped by tool id.
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id") not in seen_ids:
                    seen_ids.add(b["id"])
                    worked_since_end = True
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
                if name == "Bash":
                    _count_command(commands, read_at, repeats, inp.get("command") or "", t0, t - t0)
                if name == "AskUserQuestion":
                    question_wait_s.append(round(t - t0))
                    answers = tur.get("answers") or {}
                    for q in asked.get(tid, []):
                        _add_owner(owner, seen_owner,
                                   _question_record(q, answers.get(q.get("question")), e["timestamp"][:10]))
            state = "tool" if open_tools else "think"
        elif prompt:
            prompts[kind] += 1
            if kind == "interrupt":
                friction["interrupts"] += 1
            for rec in _page_answers(text, e["timestamp"][:10]):
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
        "commands": {k: {f: round(x, 1) for f, x in v.items()} for k, v in commands.items()},
        "reply_gaps": {k: {"n": v["n"], "s": round(v["s"], 1)} for k, v in reply_gaps.items()},
        "question_wait_s": question_wait_s,
        "gh_repeat_reads": {"n": repeats["n"], "s": round(repeats["s"], 1)},
        "notify_gaps": {k: {"n": v["n"], "s": round(v["s"], 1)} for k, v in notify.items()},
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
    """The task records in a folder. A file that is not a record (facts.json, reports) is skipped."""
    out = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(folder).glob("*.json"))]
    return [r for r in out if isinstance(r, dict) and "time" in r and "tokens" in r]


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


def _sum_slots(records, key):
    out = defaultdict(lambda: {"n": 0, "s": 0.0})
    for r in records:
        for k, v in (r.get(key) or {}).items():
            out[k]["n"] += v["n"]
            out[k]["s"] += v["s"]
    return out


def facts(records):
    """The numbers a retro reads, reduced from the records. Every threshold in `signals` reads only these."""
    m = merge_records(records)
    b = m["time"]["buckets"]
    active = sum(v for k, v in b.items() if k != AWAY)
    gaps = _sum_slots(records, "reply_gaps")
    waits = sorted(x for r in records for x in r.get("question_wait_s", []))
    long_waits = [x for x in waits if x > LONG_WAIT_S]
    themes, headers, per_day = {}, Counter(), Counter()
    for d in m["owner_decisions"]:
        slot = themes.setdefault(d.get("theme", "other"), {"n": 0, "followed": 0, "days": set()})
        slot["n"] += 1
        slot["followed"] += d["outcome"] == "followed"
        if d.get("day"):
            slot["days"].add(d["day"])
            per_day[d["day"]] += 1
        headers[re.sub(r"\W+", " ", d["header"].lower()).strip()] += 1
    cmds = defaultdict(lambda: {"calls": 0, "s": 0.0, "pure_calls": 0, "pure_s": 0.0})
    for r in records:
        for k, v in (r.get("commands") or {}).items():
            for f, x in v.items():
                cmds[k][f] += x
    reads = {"n": sum(r.get("gh_repeat_reads", {}).get("n", 0) for r in records),
             "s": sum(r.get("gh_repeat_reads", {}).get("s", 0) for r in records)}
    out = Counter(d["outcome"] for d in m["owner_decisions"])
    answered = out["followed"] + out["overridden"] + out["custom"]
    return {
        "active_s": active, "buckets": dict(b),
        "waiting": {
            "reply": {"n": sum(v["n"] for v in gaps.values()), "total_s": sum(v["s"] for v in gaps.values()),
                      "by_kind": {k: {"n": v["n"], "s": round(v["s"])} for k, v in gaps.items()}},
            "question": {"n": len(waits), "total_s": sum(waits), "long_n": len(long_waits),
                         "long_s": sum(long_waits), "capped_s": sum(min(x, LONG_WAIT_S) for x in waits),
                         "median_s": waits[len(waits) // 2] if waits else 0},
        },
        "decisions": {
            "answered": answered, "followed": out["followed"],
            "follow_rate": round(100 * out["followed"] / answered) if answered else None,
            "themes": {k: {"n": v["n"], "followed": v["followed"], "days": sorted(v["days"])}
                       for k, v in sorted(themes.items(), key=lambda kv: -kv[1]["n"])},
            "repeated_headers": [[k, v] for k, v in headers.items() if v > 1],
            "per_day": dict(sorted(per_day.items())),
        },
        "commands": {k: {f: round(x, 1) for f, x in v.items()} for k, v in cmds.items()},
        "gh_repeat_reads": reads,
    }


def signals(f):
    """Named findings, each fired by a number in `facts`. None fires on a quiet history."""
    out = []
    reply = f["waiting"]["reply"]
    status = reply["by_kind"].get("status", {"n": 0, "s": 0})
    if status["n"] >= 10 and reply["n"] and status["n"] / reply["n"] >= 0.25:
        out.append({"id": "stops-without-asking", "n": status["n"], "s": status["s"]})
    for theme, v in f["decisions"]["themes"].items():
        if theme != "other" and v["n"] >= 3 and len(v["days"]) >= 2:
            out.append({"id": "repeated-question", "theme": theme, "n": v["n"], "days": len(v["days"]),
                        "follow_rate": round(100 * v["followed"] / v["n"])})
    q = f["waiting"]["question"]
    if q["total_s"] and q["long_s"] / q["total_s"] >= 0.5:
        out.append({"id": "open-questions-inflate-wait", "long_n": q["long_n"], "long_s": q["long_s"],
                    "total_s": q["total_s"], "capped_s": q["capped_s"]})
    reads = f["gh_repeat_reads"]
    if reads["n"] >= 10:
        out.append({"id": "gh-polling", "n": reads["n"], "s": reads["s"]})
    for name, v in f["commands"].items():
        if name.startswith("gh ") and v["pure_calls"] >= 5 and v["pure_s"] / v["pure_calls"] >= 20:
            out.append({"id": "gh-slow-call", "command": name, "calls": v["pure_calls"],
                        "mean_s": round(v["pure_s"] / v["pure_calls"])})
    days = f["decisions"]["per_day"]
    if len(days) >= 3:
        typical = sorted(days.values())[len(days) // 2]
        top = max(days.items(), key=lambda kv: kv[1])
        if top[1] >= 3 * max(typical, 1) and top[1] >= 10:
            out.append({"id": "question-surge", "day": top[0], "n": top[1], "typical": typical})
    b, active = f["buckets"], f["active_s"]
    if active and b.get("wait_machine", 0) / active >= 0.15:
        out.append({"id": "background-waits", "s": round(b["wait_machine"]),
                    "share": round(100 * b["wait_machine"] / active)})
    return out


def ranked_non_dev(records):
    """Non-development time, largest first. Hooks are left out (a second each). Question waits are capped at 30
    minutes each, and the time over the cap is listed apart as questions left open."""
    b = dict(merge_records(records)["time"]["buckets"])
    waits = [x for r in records for x in r.get("question_wait_s", [])]
    open_s = sum(max(x - LONG_WAIT_S, 0) for x in waits)
    if "wait_question" in b:
        b["wait_question"] = max(b["wait_question"] - open_s, 0)
    active = sum(v for k, v in b.items() if k != AWAY) + open_s
    skip = {AWAY, "commit_hooks", "push_hooks"}
    rows = [(LABELS.get(k, k), v) for k, v in b.items() if k not in skip and group_of(k) != "agent development"]
    rows = [("waiting on your answer (capped at 30 min each)" if l == LABELS["wait_question"] else l, v)
            for l, v in rows]
    if open_s:
        rows.append(("questions left open over 30 min", open_s))
    rows.sort(key=lambda kv: -kv[1])
    return [(label, _hm(v), 100 * v / active if active else 0.0) for label, v in rows]


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
    out.append("</table>")
    out.append(_new_sections(facts(records), e))
    out.append("</body></html>\n")
    return "\n".join(out)


def _new_sections(f, e):
    q, rp = f["waiting"]["question"], f["waiting"]["reply"]
    out = ["<h2>Waiting on you, taken apart</h2><p class=note>Replies under 30 minutes, filed by how the agent ended "
           "its turn. A reply is only owed after a question. The other kinds are the agent handing control back with "
           "nothing to decide. The kind is read from the last message by keyword, so treat it as an estimate.</p>"
           "<table><tr><th>Agent ended with</th><th class=num>Gaps</th><th class=num>Time</th></tr>"]
    names = {"asked": "a question", "blocked": "items waiting on you", "status": "a status update with nothing owed",
             "delivered": "a delivery", "finished": "a finish"}
    for k, v in sorted(rp["by_kind"].items(), key=lambda kv: -kv[1]["s"]):
        out.append(f"<tr><td>{e(names.get(k, k))}</td><td class=num>{v['n']}</td><td class=num>{_hm(v['s'])}</td></tr>")
    out.append(f"</table><p class=note>Question waits: {q['n']} calls, {_hm(q['total_s'])} in all, median "
               f"{q['median_s']}s. {q['long_n']} of them ran over 30 minutes and hold {_hm(q['long_s'])}. Capped at 30 "
               f"minutes each the total is {_hm(q['capped_s'])}.</p>")
    d = f["decisions"]
    out.append("<h2>Repeated questions</h2><p class=note>Questions and decision-page answers, grouped by theme "
               "(keyword match). A theme asked on several days with a high follow rate is a rule waiting to be "
               "written down.</p><table><tr><th>Theme</th><th class=num>Asked</th><th class=num>Days</th>"
               "<th class=num>Followed the recommendation</th></tr>")
    for theme, v in d["themes"].items():
        rate = round(100 * v["followed"] / v["n"]) if v["n"] else 0
        out.append(f"<tr><td>{e(theme)}</td><td class=num>{v['n']}</td><td class=num>{len(v['days'])}</td>"
                   f"<td class=num>{rate}%{_track(rate)}</td></tr>")
    out.append("</table>")
    out.append("<h2>Commands: own time and chained time</h2><p class=note>Own time counts only calls where the "
               "command was the whole shell command. Chained time is the span of every command that contains it, so "
               "it also holds the tests, pushes and waits chained beside it.</p><table><tr><th>Command</th>"
               "<th class=num>Calls</th><th class=num>Own calls</th><th class=num>Own time</th>"
               "<th class=num>Chained time</th><th class=num>Own mean</th></tr>")
    for name, v in sorted(f["commands"].items(), key=lambda kv: -kv[1]["s"])[:16]:
        mean = f"{v['pure_s'] / v['pure_calls']:.1f}s" if v["pure_calls"] else "-"
        out.append(f"<tr><td>{e(name)}</td><td class=num>{int(v['calls'])}</td><td class=num>{int(v['pure_calls'])}"
                   f"</td><td class=num>{_hm(v['pure_s'])}</td><td class=num>{_hm(v['s'])}</td>"
                   f"<td class=num>{mean}</td></tr>")
    out.append(f"</table><p class=note>GitHub reads repeated within 10 minutes: {f['gh_repeat_reads']['n']} calls, "
               f"{_hm(f['gh_repeat_reads']['s'])}.</p>")
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
    fx = sub.add_parser("facts")
    fx.add_argument("folder", nargs="?", default=RETRO)
    fx.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "facts":
        records = load_records(a.folder)
        f = facts(records)
        bundle = {"facts": f, "signals": signals(f), "records": len(records)}
        a.out.write_text(json.dumps(bundle, indent=2, default=list) + "\n", encoding="utf-8")
        print(f"wrote {a.out} ({len(records)} records, {len(bundle['signals'])} signals)")
        return 0
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
