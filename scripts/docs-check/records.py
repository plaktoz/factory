"""Checks that decisions and their records agree, and that tasks.md is not stale.

Run from the repo root: python3 -I scripts/docs-check/records.py .

1. Every docs/decision-pages/<name>.json (a decision page source) has a <name>.md, or an ADR in docs/adr/
   whose Source line names the page and each decision id. If it has a .md, then for each
   decision id the .md has a table row that starts with that id and names one of that
   decision's option ids (or NOT SURE), or an ADR names the page and that id (a closed row may
   be removed from the .md once its ADR exists). A page answered in the browser and pasted back is
   not durable until this passes.
2. The .html beside each .json is the rendering of it (same data), so the page cannot show
   a question the record has already closed.
3. (retired 2026-11-22) tasks.md used to name the sha `main` was at, and this check failed when it fell more than
   3 merges behind. Every merge made it stale, so it was removed; `git log origin/main` is the source for the sha.
4. A PR that docs/tasks.md calls open or blocked (the same item says "not merged", "open and
   not merged" or "blocked") must not already be merged on origin/main.
5. docs/adr/ holds only proposed ADRs (docs/process.md, the fold rule). Each one has front matter with
   status: proposed and a body. An accepted or superseded ADR is folded into a spec's Decisions table and
   its file deleted. No file under docs/design/, AGENTS.md or docs/process.md links to an ADR that is not
   a proposed ADR in docs/adr/.
6. docs/reviews/ is retired (last commit 746ec67): the folder must not exist, and
   docs/tasks.md must not name it. ADRs may still cite it; they are not edited.
7. The Log in docs/tasks.md has at most LOG_CAP entries; older ones move to docs/tasks-archive.md,
   so tasks.md stays live state a session can read whole. The merger does the move (AGENTS.md: a session does not
   edit tasks.md; its pull request body carries a "## Task record").
8. Each entry line of docs/decisions.md has the form "- YYYY-MM-DD `slug`: ... Undo: ...", so every
   choice made at the recommendation can be found and reversed.
9. A pull request merged on main since 2026-11-22 must not name an open issue in its title (AGENTS.md,
   "Close the ticket with the work"). Skipped, with a note, when `gh` cannot answer.
10. A Decisions-table row in docs/design/ or docs/process.md has a real Why and Not chosen, not a placeholder such
   as "Not recorded in the ADR" (decision_rows.py).
"""
import json, re, subprocess, sys
from pathlib import Path

LOG_CAP = 12
root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
problems = []


def rows(md):
    return [l for l in md.splitlines() if l.startswith("|")]


for src in sorted((root / "docs/decision-pages").glob("*.json")):
    doc = json.loads(src.read_text(encoding="utf-8"))
    if "decisions" not in doc:
        continue
    rec = src.with_suffix(".md")
    html = src.with_suffix(".html")
    adrs = [a.read_text(encoding="utf-8") for a in (root / "docs/adr").glob("*.md")]
    in_adr = {d["id"] for d in doc["decisions"]
              if any(f"page `docs/decision-pages/{src.name}`" in a and f"decision `{d['id']}`" in a for a in adrs)}
    if not rec.exists():
        missing = [d["id"] for d in doc["decisions"] if d["id"] not in in_adr]
        if missing:
            problems.append(f"{src.name}: no record {rec.name} and no ADR for {', '.join(missing)}")
        continue
    if html.exists():
        m = re.search(r"const DATA\s*=\s*(\{.*?\});\s*\n", html.read_text(encoding="utf-8"), re.S)
        if m is None:
            m = re.search(r"(\{\"title\".*\})", html.read_text(encoding="utf-8"))
        if m is not None:
            try:
                if json.loads(m.group(1).replace("\\u003c", "<")) != doc:
                    problems.append(f"{html.name}: differs from {src.name}; run render.py")
            except ValueError:
                pass
    table = rows(rec.read_text(encoding="utf-8"))
    for d in doc["decisions"]:
        ids = {o["id"] for o in d["options"]}
        mine = [r for r in table if re.match(rf"\|\s*{re.escape(d['id'])}\b", r)]
        if not mine:
            if d["id"] not in in_adr:
                problems.append(f"{rec.name}: no table row and no ADR for {d['id']}")
        elif not any(any(f"`{i}`" in r or i in r for i in ids) or "NOT SURE" in r for r in mine):
            problems.append(f"{rec.name}: row for {d['id']} names none of its options {sorted(ids)}")

tasks = (root / "docs/tasks.md").read_text(encoding="utf-8")
merged = subprocess.run(["git", "-C", str(root), "log", "--first-parent", "--format=%s", "origin/main"],
                        capture_output=True, text=True).stdout
merged_prs = set(re.findall(r"Merge pull request #(\d+)\b", merged))
for item in re.split(r"\n(?=\d+\. |\*\*)", tasks):
    if not re.search(r"\bnot merged\b|\bblocked on\b|\bis open\b", item):
        continue
    head = item[:200]
    for n in re.findall(r"\bPRs? #(\d+)", head):
        if n in merged_prs:
            problems.append(f"tasks.md: PR #{n} is called open or blocked but is merged on origin/main: {head[:80]!r}")

adr_dir = root / "docs/adr"
proposed = set()
for adr in sorted(p for p in adr_dir.rglob("*") if p.is_file() and p.name != "README.md"):
    rel = adr.relative_to(adr_dir).as_posix()
    if adr.suffix != ".md" or "/" in rel:
        problems.append(f"docs/adr/{rel}: only <date>-<slug>.md files sit in docs/adr/; fold or delete it")
        continue
    text = adr.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    front = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    if front is None or not front.group(2).strip():
        problems.append(f"{adr.name}: no front matter or no body; an ADR needs both")
        continue
    statuses = re.findall(r"^status:\s*[\"']?([A-Za-z]+)[\"']?\s*$", front.group(1), re.M)
    if len(statuses) != 1:
        problems.append(f"{adr.name}: needs exactly one status line, found {len(statuses)}")
    elif statuses[0] != "proposed":
        problems.append(f"{adr.name}: status is {statuses[0]}; fold it into a spec Decisions table and delete the file (docs/process.md)")
    else:
        proposed.add(adr.name)
# Specs, AGENTS.md and process.md must not depend on an ADR that is not proposed. Skills and
# calibration records may name a folded ADR as history.
scanned = [root / "AGENTS.md", root / "docs/process.md", *sorted((root / "docs/design").rglob("*.md"))]
for doc in scanned:
    if doc.exists():
        for name in set(re.findall(r"adr/(2\d{3}-[0-9a-z_-]+)(?:\.md)?", doc.read_text(encoding="utf-8"))):
            if name + ".md" not in proposed:
                problems.append(f"{doc.relative_to(root)} names docs/adr/{name}, which is not a proposed ADR; cite the Decisions row id as text")

log = tasks.split("\n## Log", 1)[1] if "\n## Log" in tasks else ""
entries = len(re.findall(r"^- 20\d\d-\d\d-\d\d", log, re.M))
if entries > LOG_CAP:
    problems.append(f"tasks.md: the Log has {entries} entries (max {LOG_CAP}); whoever merges moves the oldest to docs/tasks-archive.md")

decisions_path = root / "docs/decisions.md"
if decisions_path.exists():
    for n, line in enumerate(decisions_path.read_text(encoding="utf-8").split("\n"), 1):
        if re.match(r"- \d{4}-\d\d-\d\d ", line):
            if not re.match(r"- \d{4}-\d\d-\d\d `[a-z0-9][a-z0-9-]*`: .+ Undo: .+", line):
                problems.append(f"decisions.md:{n}: write '- YYYY-MM-DD `slug`: what was chosen, over what. Undo: how'")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue_close  # noqa: E402

github = issue_close.fetch(str(root))
if github is None:
    print("records: skipped the issue-close check (9): gh could not list pull requests and issues")
else:
    problems += issue_close.open_issue_problems(*github)

import decision_rows  # noqa: E402

for spec in sorted([*(root / "docs/design").rglob("*.md"), root / "docs/process.md"]):
    if spec.is_file():
        problems += decision_rows.placeholder_problems(spec.relative_to(root).as_posix(), spec.read_text(encoding="utf-8"))

RETIRED = "docs/reviews"
if (root / RETIRED).exists():
    problems.append(f"{RETIRED}/ exists; the folder is retired, decisions are ADRs in docs/adr/")
if RETIRED in tasks:
    problems.append(f"tasks.md names {RETIRED}; point at the ADR, or at commit 746ec67 for an old report")

for p in problems:
    print("records:", p)
print(f"records: {len(problems)} problem(s)")
sys.exit(1 if problems else 0)
