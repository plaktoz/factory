"""Measure the spec pilot (issue #56) on history that already exists. Run it from any folder:

    python3 -I scripts/spec-pilot.py [--window W ...] [--json]

The repo is the checkout this script sits in, so git and gh always read the same repository. gh is given the
checkout's origin remote with -R, so it never depends on the current folder.

W is a number with a unit: 30s, 5m, 2h or 3d. Give --window more than once to measure several windows in one run,
for example --window 1h --window 24h --window 72h. --hours H is the same as --window Hh.

A spec PR implements a [Spec] issue: it closes the issue or names it in its title (a body that only mentions the
issue, as a records PR does, is not enough). Every other PR merged
on main whose diff adds code under factory/ is a baseline. Each PR gets the same follow-up, W after its merge
(default 24h). A PR merged less than W ago is listed as "too recent" and left out; it never counts as zero.

Rework: of the lines a PR added under factory/, how many are gone or rewritten in the last first-parent commit
at or before merge + W. It is read with git blame, so a line counts as the PR's when blame at the merge names a
commit the PR brought in. Bug issues and reverts are counted too.

Needs gh (logged in) and an up-to-date origin/main.
"""
import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CODE = "factory/"
SPEC_TITLE = "[Spec]"
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_window(text):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd])", text.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError(f"{text!r}: use a number and a unit, such as 30s, 5m, 2h or 3d")
    seconds = float(m.group(1)) * UNITS[m.group(2)]
    if seconds <= 0:
        raise argparse.ArgumentTypeError(f"{text!r}: the window must be longer than zero")
    return seconds


def label(seconds):
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds % size == 0 and seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return f"{seconds:g}s"


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def git(*args):
    return run("git", "-C", str(REPO), *args)


def repo_slug(root=REPO):
    """OWNER/NAME of the origin remote, in SSH or HTTPS form, for gh -R."""
    url = run("git", "-C", str(root), "remote", "get-url", "origin").strip().removesuffix("/").removesuffix(".git")
    parts = re.split(r"[:/]", url)
    if len(parts) < 3 or not parts[-2] or not parts[-1]:
        raise SystemExit(f"no origin remote with an OWNER/NAME path in {root}: {url!r}")
    return f"{parts[-2]}/{parts[-1]}"


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


def spec_issues(slug):
    out = run("gh", "issue", "list", "-R", slug, "--state", "all", "--limit", "500", "--json", "number,title")
    return {i["number"] for i in json.loads(out) if i["title"].startswith(SPEC_TITLE)}


def merged_prs(slug):
    fields = "number,title,body,mergedAt,mergeCommit,closingIssuesReferences"
    out = run("gh", "pr", "list", "-R", slug, "--state", "merged", "--base", "main", "--limit", "500", "--json", fields)
    return [p for p in json.loads(out) if p.get("mergeCommit")]


def issue_of(pr, specs):
    closes = {i["number"] for i in pr["closingIssuesReferences"]} & specs
    named = {int(n) for n in re.findall(r"\((?:pilot #|issue |#)(\d+)\)", pr["title"])} & specs
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


def name_status(a, b):
    """Changed paths under factory/ from a to b as (status, old path, new path). Renames are followed once."""
    out = []
    for row in git("diff", "--name-status", "-M", a, b, "--", CODE).split("\n"):
        if not row:
            continue
        parts = row.split("\t")
        if parts[0].startswith("R"):
            out.append(("R", parts[1], parts[2]))
        else:
            out.append((parts[0][0], parts[1], parts[1]))
    return out


def rework(merge, end):
    """Lines the PR added under factory/ that a later commit, at or before end, removed or rewrote.

    A file renamed after the merge is followed to its new path. A file deleted after the merge counts as reworked.
    """
    base = git("rev-parse", merge + "^1").strip()
    own = set(git("rev-list", f"{base}..{merge}").split())
    later = {old: new for s, old, new in name_status(merge, end) if s == "R"}

    def follow(path):
        seen = set()
        while path in later and path not in seen:
            seen.add(path)
            path = later[path]
        return path
    added = kept = 0
    for status, _, path in name_status(base, merge):
        if status == "D":
            continue
        at_merge = [c for c in blame_commits(merge, path) if c in own]
        if not at_merge:
            continue
        added += len(at_merge)
        kept += sum(1 for c in blame_commits(end, follow(path)) if c in own)
    return added, max(0, added - kept)


def measure(seconds, now, specs, chain, prs):
    on_main = {h for h, _ in chain}
    rows, recent = [], []
    for pr in sorted(prs, key=lambda p: p["mergedAt"]):
        merge = pr["mergeCommit"]["oid"]
        if merge not in on_main:
            continue
        merged = when(pr["mergedAt"])
        issue = issue_of(pr, specs)
        end_at = merged + timedelta(seconds=seconds)
        if end_at > now:
            recent.append(pr["number"])
            continue
        added, reworked = rework(merge, commit_at(chain, end_at))
        if added == 0:
            continue
        rows.append(Row(pr["number"], "spec" if issue else "baseline", issue, pr["mergedAt"], added, reworked,
                        round(reworked / added, 3)))
    return rows, recent


def defects(slug):
    bugs = run("gh", "issue", "list", "-R", slug, "--state", "all", "--label", "bug", "--limit", "500", "--json", "number")
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
    ap.add_argument("--window", type=parse_window, action="append", metavar="W",
                    help="follow-up after each merge: 30s, 5m, 2h or 3d (repeatable)")
    ap.add_argument("--hours", type=lambda h: parse_window(f"{h}h"), action="append", metavar="H",
                    help="same as --window Hh")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    windows = (args.window or []) + (args.hours or []) or [parse_window("24h")]
    now = datetime.now(timezone.utc)
    slug = repo_slug()
    specs = spec_issues(slug)
    chain = first_parent_chain()
    prs = merged_prs(slug)
    bugs, reverts = defects(slug)
    results = []
    for seconds in windows:
        rows, recent = measure(seconds, now, specs, chain, prs)
        results.append({"window": label(seconds), "seconds": seconds, "rows": rows, "too_recent": recent,
                        "verdict": summary(rows)})
    if args.json:
        print(json.dumps({"now": now.isoformat(timespec="seconds"), "bug_issues": bugs, "reverts": reverts,
                          "windows": [{**r, "rows": [asdict(x) for x in r["rows"]]} for r in results]}, indent=1))
        return
    print(f"measured {now:%Y-%m-%d %H:%M:%S} UTC; bug issues {bugs}; reverts on main {reverts}")
    for r in results:
        print(f"\n== follow-up {r['window']} after each merge")
        print(f"{'PR':>5} {'group':9} {'issue':>6} {'merged':17} {'added':>6} {'reworked':>9} {'rate':>6}")
        for x in r["rows"]:
            issue = f"#{x.issue}" if x.issue else "-"
            print(f"#{x.pr:<4} {x.group:9} {issue:>6} {x.merged[:16]:17} {x.added:>6} {x.reworked:>9} {x.rate:>6.2f}")
        print(f"too recent for this window: {', '.join(f'#{n}' for n in r['too_recent']) or 'none'}")
        print(r["verdict"])


if __name__ == "__main__":
    main()
