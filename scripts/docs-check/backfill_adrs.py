"""One-off: write an ADR for each answered decision in docs/reviews.

Run from the repo root: python3 -I scripts/docs-check/backfill_adrs.py . [--write]
Without --write it prints what it would write and skips nothing silently.

Sources, in the order they were made:
  phase-1-decisions.md   D1..D14, P1..P4, R1..R3 (answer cell only, no option list)
  open-decisions.json/.md   R1..R3, D7 (options from the JSON, answer from the table)
  open-items.json + open-decisions.md   Q1..Q5
  rebuild-run-decisions.json   E1 (answer from docs/tasks.md log), E2 (no answer recorded: skipped)
  wave3-decisions.json/.md, wave3-open-decisions.json/.md, pr43-codex-decisions.json/.md

Each ADR is `status: accepted` because the owner chose the option on the page. Every ADR says
where the answer came from, so a reader can check it. A decision with no recorded answer is
reported and skipped, never guessed.
"""
import json, re, sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
write = "--write" in sys.argv
rev = root / "docs/reviews"
out = root / "docs/adr"

# (decision key) -> (date, slug, topic, source page, record file, row regexp)
# `key` is "<page>:<id>". Dates are the day the owner answered, from the record's own text.
def jsn(name):
    return {d["id"]: d for d in json.loads((rev / f"{name}.json").read_text(encoding="utf-8"))["decisions"]}

def table_rows(md):
    return [[c.strip() for c in l.strip().strip("|").split("|")] for l in md.splitlines() if l.startswith("|")]

def answer(md, did):
    for r in table_rows(md):
        if r and re.match(rf"{re.escape(did)}\b", r[0]):
            return r
    return None

def opt_id(cell):
    m = re.search(r"`([a-z0-9\-\[\]]+)`", cell)
    return m.group(1) if m else None

JOBS = []   # (date, slug, topic, title, page, id, answer_row, record_name)

def add_paged(page, record, date, slug_of, ids=None):
    md = (rev / f"{record}.md").read_text(encoding="utf-8")
    for did, d in jsn(page).items():
        if ids and did not in ids:
            continue
        row = answer(md, did)
        JOBS.append(dict(date=date, slug=slug_of.get(did), title=d["title"], page=page, id=did, data=d, row=row,
                         record=f"{record}.md"))

add_paged("open-decisions", "open-decisions", "2026-11-14", {
    "R1": "freeze-shared-types", "R2": "one-config-type", "R3": "repo-supplies-worktree-comparison",
    "D7": "claude-sandbox-for-workers"})
add_paged("open-items", "open-decisions", "2026-11-14", {
    "Q1": "gate-commands-run-under-srt", "Q2": "build-caches-in-task-dir", "Q3": "commands-are-lists-only",
    "Q4": "runspec-script-or-python", "Q5": "linux-and-oauth-testing"})
add_paged("pilot-repo-decisions", "phase-1-decisions", "2026-11-14", {
    "P1": "checkpoint-commits-stay-local", "P2": "cleanup-runs-repo-comparison-first",
    "P3": "pilot-starts-in-phase-1a", "P4": "record-the-model-the-harness-reports"})
add_paged("wave3-decisions", "wave3-decisions", "2026-11-15", {
    "D1": "accept-draft-report-schemas", "D2": "bug-fix-loop-count-3", "D3": "keep-reviewer-eval-on-main"})
add_paged("wave3-open-decisions", "wave3-open-decisions", "2026-11-15", {
    "D1": "keep-history-with-work-email", "D2": "dashboard-plain-page-in-phase-1a"})
add_paged("pr43-codex-decisions", "pr43-codex-decisions", "2026-11-15", {
    "D1": "codex-sandbox-residual-risk-accepted"}, ids={"D1"})  # D2 held a PR; it is an action, not a rule
# E1: the record is the tasks.md log, not a table
JOBS.append(dict(date="2026-11-15", slug="rebuild-run-from-last-snapshot", title=jsn("rebuild-run-decisions")["E1"]["title"],
                 page="rebuild-run-decisions", id="E1", data=jsn("rebuild-run-decisions")["E1"],
                 row=["E1", "", "`snapshot-event`: a `run_snapshot` event after each change, carrying the whole run; a rebuild replays only the last one"],
                 record="../tasks.md (Log, 2026-11-15 wave 1, module 6A)"))

# phase-1 D1..D14: answer cell only
p1 = (rev / "phase-1-decisions.md").read_text(encoding="utf-8")
P1_SLUG = {"D1": "run-lock-is-an-os-file-lock", "D2": "cmd-task-non-zero-exit-is-a-check-failure",
           "D3": "dependent-tasks-branch-from-their-dependency", "D4": "one-decision-file-per-stage-and-visit",
           "D5": "dashboard-writes-need-token-host-and-origin", "D6": "macos-and-linux-in-phase-1",
           "D8": "personal-setup-kept-out-by-cli-flags", "D9": "factory-writes-its-own-stage-skills",
           "D10": "phase-1a-walking-skeleton-first", "D11": "snapshot-the-kit-per-run",
           "D12": "crash-recovery-resets-to-last-checkpoint", "D13": "outages-retry-then-block",
           "D14": "restart-from-progress-md"}
for did, slug in P1_SLUG.items():
    row = answer(p1, did)
    JOBS.append(dict(date="2026-11-14", slug=slug, title=row[1] if row else did, page="phase-1-decisions", id=did,
                     data=None, row=row, record="phase-1-decisions.md"))

skipped = []
for j in JOBS:
    if j["row"] is None:
        skipped.append(f'{j["page"]}:{j["id"]} (no answer row in {j["record"]})')
        continue
    j["name"] = f'{j["date"]}-{j["slug"]}'
ok = [j for j in JOBS if j["row"] is not None]


# phase-1-decisions.md says "All four took the recommended option" for the pilot page.
RECOMMENDED_WAS_CHOSEN = {"pilot-repo-decisions": {"P1", "P2", "P3", "P4"}}
# Q5 was NOT SURE on the page and answered in round 3 (docs/reviews/open-decisions.md, Q5 row and notes).
DECISION_TEXT = {("open-items", "Q5"): "OAuth login is out of scope (phase 1 uses a key or gateway token). Linux is a pre-pilot check: `doctor` must pass the canary on Linux before the phase 1a pilot."}


def body(j):
    d, row = j["data"], j["row"]
    title = j["title"] if d else row[1]
    ids = {o["id"] for o in d["options"]} if d else set()
    chosen = next((c for c in row[1:] if opt_id(c) in ids), None)
    if chosen is None:                 # no option id in the row: take the answer cell by layout
        chosen = row[2] if len(row[0].split()) == 1 and len(row) > 2 else row[1]
    cid = opt_id(chosen) if opt_id(chosen) in ids else None
    if d and cid is None and j["id"] in RECOMMENDED_WAS_CHOSEN.get(j["page"], ()):
        cid = next(o["id"] for o in d["options"] if o.get("recommended"))   # the record says so
    if d and cid and re.fullmatch(r"`[^`]+`(\s*\(.*\))?", chosen.strip()):
        name = next(o["name"] for o in d["options"] if o["id"] == cid)
        note = re.search(r"\((.*)\)", chosen)
        chosen = name + (f" ({note.group(1)})" if note else "")
    if (j["page"], j["id"]) in DECISION_TEXT:
        chosen = DECISION_TEXT[(j["page"], j["id"])]
    lines = ["---", "scope: repo", "repo: factory", f"topic: {j['slug']}", "status: accepted", "supersedes: []", "---", "",
             f"# {title}", "", "## Decision", ""]
    lines.append(re.sub(r"^`[^`]+`:?\s*", "", chosen).strip() or chosen)
    if cid:
        lines += ["", f"Chosen option: `{cid}`."]
    lines.append("")
    if d:
        picked = next((o for o in d["options"] if o["id"] == cid), None)
        against_advice = picked is not None and not picked.get("recommended")
        lines += ["## Context", "", d.get("context", "").strip(), ""]
        lines += ["## Options considered", ""]
        for o in d["options"]:
            tags = (" (chosen)" if o["id"] == cid else "") + (" (recommended)" if o.get("recommended") else "")
            lines.append(f"- **`{o['id']}`**{tags}: {o['name']}")
            for p in o.get("pros", []):
                lines.append(f"  - For: {p}")
            for c in o.get("cons", []):
                lines.append(f"  - Against: {c}")
        lines.append("")
        if d.get("why"):
            who = "the recommended option, which the owner did not choose" if against_advice else "the chosen option"
            lines += ["## Why", "", f"The page's reason is for {who}. The owner's own reason is not recorded.",
                      "" if not against_advice else "", d["why"].strip(), ""]
    lines += ["## Source", "",
              f"Backfilled on 2026-11-16 from `docs/reviews/{j['record']}`, decision `{j['id']}`"
              + (f", page `docs/reviews/{j['page']}.json`" if d else "")
              + f". The owner chose this on {j['date']}; the answer is the record's, not new.", ""]
    return "\n".join(lines)


for j in ok:
    text = body(j)
    path = out / f"{j['name']}.md"
    if path.exists():
        skipped.append(f"{path.name} already exists; not overwritten")
        continue
    if write:
        path.write_text(text, encoding="utf-8")
    print(("wrote " if write else "would write ") + path.name)
for s in skipped:
    print("skipped:", s)
print(f"{len(ok)} decisions, {len(skipped)} skipped")
