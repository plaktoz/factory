"""How much of the work is product code. Run from the repo root: python3 -I scripts/code-share.py [days]

Prints, for the last N days (default 7): non-merge commits that touch factory/ against those that do not, and ADRs
written per day. Target: more than 60% of commits touch factory/ (the decide-by-default row in docs/process.md).
"""
import subprocess, sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

TARGET = 0.60
days = int(sys.argv[1]) if len(sys.argv) > 1 else 7


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


log = git("log", f"--since={days}.days", "--no-merges", "--format=@%h", "--name-only")
commits = [c.split("\n") for c in log.split("@")[1:]]
code = sum(1 for c in commits if any(f.startswith("factory/") for f in c[1:]))
total = len(commits)
share = code / total if total else 0.0
print(f"last {days} days: {code} of {total} commits touch factory/ ({share:.0%}; target > {TARGET:.0%})")

start = (date.today() - timedelta(days=days)).isoformat()
adrs = Counter(p.name[:10] for p in Path("docs/adr").glob("*.md") if p.name[:10] >= start)
print("ADRs per day:", ", ".join(f"{d} {n}" for d, n in sorted(adrs.items())) or "none")
log_md = Path("docs/decisions.md")
logged = log_md.read_text(encoding="utf-8").count("\n- 20") if log_md.exists() else 0
print(f"choices decided at the recommendation (docs/decisions.md): {logged}")
