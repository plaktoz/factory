"""Record what one task cost, then read the records later. Run from the repo root:

    python3 -I scripts/task-record.py write [--base origin/main]
    python3 -I scripts/task-record.py report [docs/retro]

`write` makes docs/retro/<branch>.json from two sources that already exist: the Claude Code transcripts of the
sessions that worked on this branch (time, tokens, questions asked, permission prompts) and git (commits,
Decision trailers, ADRs, lines changed by kind). It is derived, so run it again after more work and it replaces
the file. A branch has one file and no other branch writes it, so merges do not conflict. `report` totals a folder.

Sessions are the ones in this worktree's Claude project folder whose gitBranch is this branch, plus any session
named by an Agent-Run trailer. Waiting is counted three ways. A turn wait is the gap from a finished turn to your
next prompt. A question wait is the time an AskUserQuestion stays open. A permission wait is the time a tool call
stays open when a person, not the config, decided it. A permission wait includes the tool's run time.
Tokens are counted once per message id: the transcript repeats a message's usage once per content block.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RETRO = "docs/retro"
TOKEN_KEYS = {"input": "input_tokens", "output": "output_tokens", "cache_creation": "cache_creation_input_tokens",
              "cache_read": "cache_read_input_tokens"}
KINDS = ("product", "spec", "process")


def classify(path):
    """product: what ships in the kit. spec: the design. process: how this repo is run. None: not counted."""
    if path.startswith(RETRO + "/"):
        return None
    if path.startswith("factory/"):
        return "product"
    if path.startswith("docs/design/"):
        return "spec"
    return "process"


def _ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def _blocks(message):
    content = message.get("content")
    return content if isinstance(content, list) else []


def _is_prompt(entry):
    m = entry.get("message") or {}
    if entry.get("type") != "user" or entry.get("isSidechain") or entry.get("isMeta"):
        return False
    content = m.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    return any(b.get("type") == "text" for b in _blocks(m)) and not any(b.get("type") == "tool_result" for b in _blocks(m))


def _tokens(paths):
    """Sum usage once per message id across the given transcripts."""
    seen, total = {}, dict.fromkeys(TOKEN_KEYS, 0)
    for p in paths:
        for raw in Path(p).read_text(encoding="utf-8").splitlines():
            e = json.loads(raw)
            m = e.get("message")
            if e.get("type") == "assistant" and isinstance(m, dict) and m.get("usage"):
                seen[(str(p), m.get("id"))] = m["usage"]
    for usage in seen.values():
        for k, field in TOKEN_KEYS.items():
            total[k] += usage.get(field) or 0
    return total


def read_session(path, subagent_paths):
    """Time, waiting and tokens of one session transcript, plus the tokens of its subagents."""
    entries = [json.loads(raw) for raw in Path(path).read_text(encoding="utf-8").splitlines()]
    stamps = [_ts(e["timestamp"]) for e in entries if e.get("timestamp")]
    started = {}
    out = {"wait_turn_s": 0.0, "wait_question_s": 0.0, "wait_permission_s": 0.0, "questions": 0,
           "permission_prompts": 0, "user_prompts": 0}
    turn_ended = None
    for e in entries:
        t = _ts(e["timestamp"]) if e.get("timestamp") else None
        m = e.get("message") if isinstance(e.get("message"), dict) else {}
        if e.get("type") == "assistant":
            for b in _blocks(m):
                if b.get("type") == "tool_use":
                    started[b["id"]] = (t, b["name"])
            turn_ended = t if m.get("stop_reason") == "end_turn" else None
        elif _is_prompt(e):
            out["user_prompts"] += 1
            if turn_ended is not None and t is not None:
                out["wait_turn_s"] += t - turn_ended
            turn_ended = None
        elif e.get("type") == "user":
            asked_by = (e.get("permissionDecision") or {}).get("source", "config")
            for b in _blocks(m):
                if b.get("type") != "tool_result" or b.get("tool_use_id") not in started:
                    continue
                t0, name = started[b["tool_use_id"]]
                if name == "AskUserQuestion":
                    out["questions"] += 1
                    out["wait_question_s"] += t - t0
                elif asked_by != "config":
                    out["permission_prompts"] += 1
                    out["wait_permission_s"] += t - t0
    out["wall_s"] = (max(stamps) - min(stamps)) if stamps else 0.0
    out["tokens"] = _tokens([path])
    out["subagent_tokens"] = _tokens(subagent_paths)
    return {k: (round(v, 1) if isinstance(v, float) else v) for k, v in out.items()}


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def read_git(repo, base):
    """Commits, decisions and lines changed on HEAD since it left `base`."""
    commits = _git(repo, "log", f"{base}..HEAD", "--no-merges", "--format=%H%x1f%B%x1e").split("\x1e")
    bodies = [c.split("\x1f", 1)[1] for c in commits if "\x1f" in c]
    lines = dict.fromkeys(KINDS, 0)
    decision_lines = 0
    for row in _git(repo, "diff", "--numstat", f"{base}...HEAD").splitlines():
        added, _, path = row.split("\t", 2)
        if added == "-":
            continue
        kind = classify(path)
        if kind:
            lines[kind] += int(added)
        if path == "docs/decisions.md":
            decision_lines += int(added)
    names = _git(repo, "diff", "--name-status", f"{base}...HEAD").splitlines()
    adrs = [r for r in names if r.startswith("A\t") and re.fullmatch(r"docs/adr/\d{4}-.*\.md", r.split("\t")[1])]
    return {"commits": len(bodies),
            "decision_trailers": sum(len(re.findall(r"^Decision:", b, re.M)) for b in bodies),
            "adrs_added": len(adrs), "decision_lines_added": decision_lines, "lines": lines,
            "agent_runs": sorted({r for b in bodies for r in re.findall(r"^Agent-Run: (\S+)", b, re.M)})}


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


def build_record(root, base, sessions_root):
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    g = read_git(root, base)
    sessions = find_sessions(root, branch, g["agent_runs"], sessions_root)
    parts = [read_session(p, sorted((p.parent / sid / "subagents").glob("agent-*.jsonl"))) for sid, p in sessions.items()]
    add = lambda key: round(sum(s[key] for s in parts), 1)
    wait = {"turn_s": add("wait_turn_s"), "question_s": add("wait_question_s"), "permission_s": add("wait_permission_s")}
    tok = lambda key: {k: sum(s[key][k] for s in parts) for k in TOKEN_KEYS}
    return {"task": branch.split("/")[-1], "branch": branch, "base": base, "sessions": sorted(sessions),
            "wall_s": add("wall_s"), "wait_s": round(sum(wait.values()), 1), "wait": wait,
            "tokens": tok("tokens"), "subagent_tokens": tok("subagent_tokens"),
            "user_prompts": sum(s["user_prompts"] for s in parts),
            "permission_prompts": sum(s["permission_prompts"] for s in parts),
            "decisions": {"questions": sum(s["questions"] for s in parts), "trailers": g["decision_trailers"],
                          "adrs_added": g["adrs_added"], "lines_added": g["decision_lines_added"]},
            "commits": g["commits"], "lines": g["lines"], "agent_runs": g["agent_runs"]}


def load_records(folder):
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(folder).glob("*.json"))]


def _hm(seconds):
    m = round(seconds / 60)
    return f"{m // 60}h{m % 60:02d}m"


def _k(n):
    return f"{n / 1000:.0f}k" if n < 1_000_000 else f"{n / 1_000_000:.1f}M"


def _row(name, rs):
    s = lambda f: sum(f(r) for r in rs)
    d = lambda r, k: r["decisions"][k]
    lines = {k: s(lambda r: r["lines"][k]) for k in KINDS}
    share = round(100 * lines["process"] / max(1, sum(lines.values())))
    tok = lambda key, k: s(lambda r: r[key][k])
    return [name, _hm(s(lambda r: r["wall_s"])), _hm(s(lambda r: r["wait_s"])),
            str(s(lambda r: d(r, "questions") + d(r, "trailers") + d(r, "adrs_added"))),
            str(s(lambda r: d(r, "adrs_added"))),
            _k(tok("tokens", "output") + tok("subagent_tokens", "output")),
            _k(tok("tokens", "input") + tok("tokens", "cache_creation") + tok("subagent_tokens", "input") + tok("subagent_tokens", "cache_creation")),
            _k(tok("tokens", "cache_read") + tok("subagent_tokens", "cache_read")), f"{share}%"]


def render_report(records):
    head = ["task", "wall", "waiting", "decisions", "adrs", "out", "in+write", "cache-read", "process lines"]
    rows = [head] + [_row(r["task"], [r]) for r in records] + [_row("TOTAL", records)]
    w = [max(len(r[i]) for r in rows) for i in range(len(head))]
    fmt = lambda r: "  ".join(c.ljust(w[i]) for i, c in enumerate(r))
    return "\n".join([fmt(rows[0]), *map(fmt, rows[1:])]) + (
        "\n\ndecisions = questions asked + Decision trailers + ADRs added. waiting = turn + question + permission waits."
        "\nprocess lines = share of added lines outside factory/ and docs/design/.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write")
    w.add_argument("--base", default="origin/main")
    w.add_argument("--sessions-root", type=Path, default=Path.home() / ".claude/projects")
    r = sub.add_parser("report")
    r.add_argument("folder", nargs="?", default=RETRO)
    a = ap.parse_args(argv)
    if a.cmd == "report":
        print(render_report(load_records(a.folder)))
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
