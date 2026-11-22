"""Measure the spec pilot (issue #56) on history that already exists. Run from the repo root:

    python3 -I scripts/spec-pilot.py [--hours H] [--json]

A spec PR implements a [Spec] issue: it closes the issue or names it in its title (a body that only mentions the
issue, as a records PR does, is not enough). Every other PR merged
on main whose diff adds code under factory/ is a baseline. Each PR gets the same follow-up, H hours from its merge
(default 24). A PR merged less than H hours ago is listed as "too recent" and left out; it never counts as zero.

Rework: of the lines a PR added under factory/, how many are gone or rewritten in the last first-parent commit
at or before merge + H. It is read with git blame, so a line counts as the PR's when blame at the merge names a
commit the PR brought in. Bug issues and reverts are counted too.

Needs gh (logged in) and an up-to-date origin/main.
"""
import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

CODE = "factory/"
SPEC_TITLE = "[Spec]"


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def git(*args):
    return run("git", *args)


def when(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


@dataclass
class Row:
    pr: int
    group: str
    issue: int | None
    merged: str
    added: int
    reworked: int
    rate: float


def spec_issues():
    out = run("gh", "issue", "list", "--state", "all", "--limit", "500", "--json", "number,title")
    return {i["number"] for i in json.loads(out) if i["title"].startswith(SPEC_TITLE)}


def merged_prs():
    fields = "number,title,body,mergedAt,mergeCommit,closingIssuesReferences"
    out = run("gh", "pr", "list", "--state", "merged", "--base", "main", "--limit", "500", "--json", fields)
    return [p for p in json.loads(out) if p.get("mergeCommit")]


def issue_of(pr, specs):
    closes = {i["number"] for i in pr["closingIssuesReferences"]} & specs
    named = {int(n) for n in re.findall(r"(?:#|issue )(\d+)", pr["title"])} & specs
    found = closes or named
    return min(found) if found else None


def blame_commits(rev, path):
    try:
        out = git("blame", "--line-porcelain", rev, "--", path)
    except subprocess.CalledProcessError:
        return []
    return [line[:40] for line in out.split("\n") if re.match(r"^[0-9a-f]{40} \d+ \d+", line)]


def first_parent_chain():
    rows = git("log", "--first-parent", "--format=%H %cI", "origin/main").split("\n")
    return [(h, when(t)) for h, t in (r.split() for r in rows if r)]


def commit_at(chain, moment):
    return next((h for h, t in chain if t <= moment), None)


def rework(merge, end):
    base = git("rev-parse", merge + "^1").strip()
    own = set(git("rev-list", f"{base}..{merge}").split())
    files = [f for f in git("diff", "--name-only", "--diff-filter=AM", base, merge, "--", CODE).split() if f]
    added = kept = 0
    for path in files:
        at_merge = [c for c in blame_commits(merge, path) if c in own]
        if not at_merge:
            continue
        added += len(at_merge)
        kept += sum(1 for c in blame_commits(end, path) if c in own)
    return added, max(0, added - kept)


def measure(hours, now):
    specs = spec_issues()
    chain = first_parent_chain()
    on_main = {h for h, _ in chain}
    rows, recent = [], []
    for pr in sorted(merged_prs(), key=lambda p: p["mergedAt"]):
        merge = pr["mergeCommit"]["oid"]
        if merge not in on_main:
            continue
        merged = when(pr["mergedAt"])
        issue = issue_of(pr, specs)
        if merged + timedelta(hours=hours) > now:
            recent.append(pr["number"])
            continue
        added, reworked = rework(merge, commit_at(chain, merged + timedelta(hours=hours)))
        if added == 0:
            continue
        rows.append(Row(pr["number"], "spec" if issue else "baseline", issue, pr["mergedAt"], added, reworked,
                        round(reworked / added, 3)))
    return rows, recent


def defects():
    bugs = run("gh", "issue", "list", "--state", "all", "--label", "bug", "--limit", "500", "--json", "number")
    reverts = [l for l in git("log", "--format=%s", "origin/main").split("\n") if l.lower().startswith("revert")]
    return len(json.loads(bugs)), len(reverts)


def summary(rows):
    base = sorted(r.rate for r in rows if r.group == "baseline")
    spec = [r.rate for r in rows if r.group == "spec"]
    if not base or not spec:
        return "inconclusive: a group has no PR with a full follow-up window"
    zero = sum(1 for b in base if b == 0) / len(base)
    if zero > 0.5:
        return (f"inconclusive: {zero:.0%} of {len(base)} baseline PRs show no rework in this window, so a spec rate "
                f"of 0 is what both groups would show; a longer window is needed")
    lo, hi = base[0], base[-1]
    outside = [s for s in spec if s < lo or s > hi]
    if not outside:
        return f"no evidence either way: every spec rate is inside the baseline range {lo:.2f} to {hi:.2f}"
    return f"spec rates outside the baseline range {lo:.2f} to {hi:.2f}: {outside}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    rows, recent = measure(args.hours, now)
    bugs, reverts = defects()
    verdict = summary(rows)
    if args.json:
        print(json.dumps({"hours": args.hours, "now": now.isoformat(timespec="seconds"), "rows": [asdict(r) for r in rows],
                          "too_recent": recent, "bug_issues": bugs, "reverts": reverts, "verdict": verdict}, indent=1))
        return
    print(f"follow-up {args.hours:g} h from each merge, measured {now:%Y-%m-%d %H:%M} UTC")
    print(f"{'PR':>5} {'group':9} {'issue':>6} {'merged':17} {'added':>6} {'reworked':>9} {'rate':>6}")
    for r in rows:
        issue = f"#{r.issue}" if r.issue else "-"
        print(f"#{r.pr:<4} {r.group:9} {issue:>6} {r.merged[:16]:17} {r.added:>6} {r.reworked:>9} {r.rate:>6.2f}")
    print(f"too recent for a full window: {', '.join(f'#{n}' for n in recent) or 'none'}")
    print(f"bug issues: {bugs}; reverts on main: {reverts}")
    print(verdict)


if __name__ == "__main__":
    main()
