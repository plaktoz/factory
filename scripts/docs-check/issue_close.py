"""A merged pull request must not leave the issue its title names open (AGENTS.md, "Close the ticket with the work").

The title is the claim of what a pull request finishes: "Stop a task after max_interruptions crashes (#87)". A body
may name an issue it only touches, so the body is not read. A pull request that only touches an issue writes
`Refs #n` in its body and leaves the number out of the title.

`open_issue_problems` is pure. `fetch` asks GitHub through `gh` and returns None when `gh` cannot answer, so the check
is skipped on a machine with no network or no login and never fails for that reason.
"""
from __future__ import annotations

import json
import re
import subprocess

LIMIT = 200  # how many pull requests and issues to ask GitHub for; a full list is reported, not hidden
CLOSE_FROM = "2026-11-22"  # the day the rule was written; earlier pull requests are exempt


def open_issue_problems(merged_prs: list[dict], open_issues: set[int]) -> list[str]:
    """One problem per issue a merged pull request's title names that is still open."""
    problems = []
    for pr in merged_prs:
        if (pr.get("mergedAt") or "")[:10] < CLOSE_FROM:
            continue
        for n in sorted({int(m) for m in re.findall(r"#(\d+)", pr.get("title") or "")}):
            if n in open_issues:
                problems.append(f"PR #{pr['number']} is merged and its title names issue #{n}, which is still open: "
                                f"close it, or name it as `Refs #{n}` in the body and not in the title")
    return problems


def _gh(args: list[str], cwd: str) -> list | None:
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, check=True, cwd=cwd, timeout=20).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def fetch(root: str) -> tuple[list[dict], set[int]] | None:
    """(merged pull requests on main, numbers of open issues), or None when gh cannot answer."""
    prs = _gh(["pr", "list", "--state", "merged", "--base", "main", "--limit", str(LIMIT),
               "--json", "number,title,mergedAt"], root)
    issues = _gh(["issue", "list", "--state", "open", "--limit", str(LIMIT), "--json", "number"], root)
    if prs is None or issues is None or len(prs) >= LIMIT or len(issues) >= LIMIT:
        return None  # a full list may have been cut short, so the check says it was skipped, not that it passed
    return prs, {i["number"] for i in issues}
