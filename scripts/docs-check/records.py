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
3. docs/tasks.md says "`main` is at `<sha>`"; that commit must be on first-parent main and at most
   MAX_BEHIND merges behind it.
4. A PR that docs/tasks.md calls open or blocked (the same item says "not merged", "open and
   not merged" or "blocked") must not already be merged on origin/main.
5. Every ADR dated TRACKED_FROM or later is named by file name in docs/tasks.md (Log or task), so
   the session that records a decision also updates the task list.
"""
import json, re, subprocess, sys
from pathlib import Path

MAX_BEHIND = 3
TRACKED_FROM = "2026-11-16"  # the 33 ADRs backfilled on 2026-11-14 and 15 are exempt
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
m = re.search(r"`main` is at `([0-9a-f]{7,40})`", tasks)
if m:
    try:
        chain = subprocess.run(["git", "-C", str(root), "rev-list", "--first-parent", "origin/main"],
                               capture_output=True, text=True, check=True).stdout.split()
        full = subprocess.run(["git", "-C", str(root), "rev-parse", m.group(1)],
                              capture_output=True, text=True, check=True).stdout.strip()
        behind = chain.index(full) if full in chain else None
        if behind is None:
            problems.append(f"tasks.md: `main` is at {m.group(1)}, which is not on origin/main's first-parent line")
        elif behind > MAX_BEHIND:
            problems.append(f"tasks.md: `main` is at {m.group(1)}, {behind} merges behind origin/main (max {MAX_BEHIND})")
    except subprocess.CalledProcessError as e:
        problems.append(f"tasks.md: cannot check the main sha: {e.stderr.strip() or e}")
else:
    problems.append("tasks.md: no line of the form 'main is at `<sha>`'")

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

for adr in sorted((root / "docs/adr").glob("*.md")):
    if adr.name[:10] >= TRACKED_FROM and adr.name not in tasks:
        problems.append(f"tasks.md does not name {adr.name}; a decision is not carried through until the task list says so")

for p in problems:
    print("records:", p)
print(f"records: {len(problems)} problem(s)")
sys.exit(1 if problems else 0)
