"""Turn a retro report (findings with options) into <name>.md and <name>.html beside it.

    python3 -I render.py <report.json> <facts.json>

facts.json is what `task-record.py facts` writes: {"facts": ..., "signals": [...]}. Every evidence line in a finding
names a path into those facts, and the renderer prints the value found there, so a number in the report cannot be
one the data does not hold. Exits 1 and prints every problem when the report breaks a rule.
"""
import html as htmllib
import json
import re
import sys
from pathlib import Path

TRIGGERS = {"reopens-decision", "changes-scope", "costly-to-reverse", "no-clear-winner", "routine"}
IMPACT = {"high": 0, "medium": 1, "low": 2}
BUILDER = re.compile(r"\b(script|module|schema|json|flag|function|regex|parser|hook script)\b", re.I)


def fail(problems):
    for p in problems:
        print(f"render: {p}", file=sys.stderr)
    sys.exit(1)


def lookup(facts, path):
    node = facts
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise KeyError(path)
    return node


def fmt(v):
    if isinstance(v, float):
        return f"{v:,.1f}"
    if isinstance(v, int):
        return f"{v:,}"
    return json.dumps(v) if isinstance(v, (dict, list)) else str(v)


def need_text(d, key, where, problems):
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        problems.append(f"{where}: '{key}' must be non-empty text")
        return ""
    return v


def validate(report, facts, fired):
    problems = []
    for key in ("title", "intro", "period", "storage_key"):
        need_text(report, key, "report", problems)
    limits = report.get("limits")
    if not isinstance(limits, list) or not [x for x in limits if isinstance(x, str) and x.strip()]:
        problems.append("report: 'limits' must list at least one thing the data could not show")
    findings = report.get("findings")
    if not isinstance(findings, list) or not findings:
        problems.append("report: 'findings' must hold at least one finding")
        return problems
    seen = set()
    for i, f in enumerate(findings):
        where = f"finding {f.get('id', i)}"
        fid = need_text(f, "id", where, problems)
        if fid in seen:
            problems.append(f"{where}: id repeated")
        seen.add(fid)
        for key in ("title", "category", "today", "after", "why", "trigger_detail"):
            need_text(f, key, where, problems)
        if f.get("impact") not in IMPACT:
            problems.append(f"{where}: impact must be high, medium or low")
        if f.get("trigger") not in TRIGGERS:
            problems.append(f"{where}: trigger must be one of {sorted(TRIGGERS)}")
        sig = f.get("signal")
        if sig != "judgment" and sig not in fired:
            problems.append(f"{where}: signal '{sig}' did not fire; name a fired signal or write 'judgment'")
        ev = f.get("evidence")
        if not isinstance(ev, list) or not ev:
            problems.append(f"{where}: evidence must list at least one fact")
        for e in ev or []:
            try:
                lookup(facts, e.get("fact", ""))
            except KeyError:
                problems.append(f"{where}: evidence path '{e.get('fact')}' is not in the facts")
            need_text(e, "label", f"{where} evidence", problems)
        opts = f.get("options")
        if not isinstance(opts, list) or not 2 <= len(opts) <= 4:
            problems.append(f"{where}: needs 2 to 4 options")
            continue
        if sum(1 for o in opts if o.get("recommended")) != 1:
            problems.append(f"{where}: exactly one option must be recommended")
        ids = [o.get("id") for o in opts]
        if len(set(ids)) != len(ids):
            problems.append(f"{where}: option ids repeat")
        for o in opts:
            ow = f"{where} option {o.get('id')}"
            for key in ("id", "name", "see", "asks"):
                need_text(o, key, ow, problems)
            for key in ("pros", "cons"):
                v = o.get(key)
                if not isinstance(v, list) or not [x for x in v if isinstance(x, str) and x.strip()]:
                    problems.append(f"{ow}: {key} must list at least one item")
            if BUILDER.search(o.get("see", "")):
                problems.append(f"{ow}: 'see' uses a builder word; say what the owner will notice")
    return problems


def evidence_rows(f, facts):
    return [(e["label"], fmt(lookup(facts, e["fact"])), e["fact"]) for e in f["evidence"]]


def option_line(f, o):
    return f"{f['id']} {f['title']}: {o['name']} [{o['id']}]"


def markdown(report, facts):
    out = [f"# {report['title']}", "", f"{report['intro']}", "", f"Period: {report['period']}.", "",
           "## What this data cannot show", ""]
    out += [f"- {x}" for x in report["limits"]]
    findings = sorted(report["findings"], key=lambda f: IMPACT[f["impact"]])
    out += ["", "## Findings, most important first", ""]
    out += ["| Id | Finding | Category | Impact | Asked because |", "| --- | --- | --- | --- | --- |"]
    out += [f"| {f['id']} | {f['title']} | {f['category']} | {f['impact']} | {f['trigger']} |" for f in findings]
    for f in findings:
        out += ["", f"## {f['id']}. {f['title']}", "",
                f"Category: {f['category']}. Impact: {f['impact']}. Asked because: {f['trigger']} "
                f"({f['trigger_detail']}). Signal: {f['signal']}.", "", "**Evidence**", ""]
        out += [f"- {label}: **{val}** (`{path}`)" for label, val, path in evidence_rows(f, facts)]
        out += ["", f"**Today.** {f['today']}", "", f"**After.** {f['after']}", "", "**Options**", ""]
        for o in f["options"]:
            rec = " (recommended)" if o.get("recommended") else ""
            out += [f"### {o['name']} [{o['id']}]{rec}", "", f"You will see: {o['see']}", "",
                    f"It asks of you: {o['asks']}", "", "Pros:", ""]
            out += [f"- {x}" for x in o["pros"]]
            out += ["", "Cons:", ""]
            out += [f"- {x}" for x in o["cons"]]
            out.append("")
        out += [f"**Why the recommendation.** {f['why']}"]
    out += ["", "## Prompt", "", "Copy the block below into Claude Code. Change a line to pick another option, or "
            "write `NOT SURE. Question: ...` to ask first.", "", "```text",
            "Apply these retro decisions. For each, make the change in the repo, record it by cost "
            "(commit message, docs/decisions.md line, or a proposed ADR), and report what you did.", ""]
    for f in findings:
        rec = next(o for o in f["options"] if o.get("recommended"))
        out.append(f"{option_line(f, rec)} (recommended)")
    out += ["```", ""]
    return "\n".join(out)


def build_html(report, facts):
    tpl = (Path(__file__).parent / "report.html").read_text(encoding="utf-8")
    view = dict(report)
    view["findings"] = sorted(report["findings"], key=lambda f: IMPACT[f["impact"]])
    for f in view["findings"]:
        f["rows"] = [{"label": a, "value": b, "path": c} for a, b, c in evidence_rows(f, facts)]
    data = json.dumps(view, ensure_ascii=False).replace("<", "\\u003c")
    title = htmllib.escape(report["title"])
    return tpl.replace("__DATA__", data).replace("__TITLE__", title)


def main():
    if len(sys.argv) != 3:
        fail(["usage: render.py <report.json> <facts.json>"])
    src, fsrc = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        report = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:
        fail([f"cannot read report {src}: {e}"])
    try:
        bundle = json.loads(fsrc.read_text(encoding="utf-8"))
        facts, fired = bundle["facts"], {s["id"] for s in bundle["signals"]}
    except Exception as e:
        fail([f"cannot read facts {fsrc}: {e}"])
    problems = validate(report, facts, fired)
    if problems:
        fail(problems)
    src.with_suffix(".md").write_text(markdown(report, facts), encoding="utf-8")
    src.with_suffix(".html").write_text(build_html(report, facts), encoding="utf-8")
    print(f"render: {len(report['findings'])} findings -> {src.with_suffix('.md').name}, {src.with_suffix('.html').name}")


main()
