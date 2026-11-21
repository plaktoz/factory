"""Run the repo's own spec checks and say whether one file may be scored.

Run from the repo root: python3 -I .claude/skills/revise-spec/scripts/precheck.py <file>

Prints a verdict line, then one line per problem. Exit 0: the file may be scored. Exit 1: it may not.
Exit 2: bad usage.

A check blocks scoring only when it reports a problem about this file. A problem elsewhere in the repo
(for example a stale `main` sha in docs/tasks.md) is printed as a note and does not block, because it says
nothing about the file being scored. The existing scripts are not changed; this wrapper reads their output.
"""
import re, subprocess, sys
from pathlib import Path

ROOT = Path.cwd()
CHECKS = ROOT / "scripts/docs-check"


def run(*args):
    p = subprocess.run([sys.executable, "-I", *args], capture_output=True, text=True, cwd=ROOT)
    return p.returncode, (p.stdout + p.stderr).splitlines()


def main():
    if len(sys.argv) != 2:
        print("usage: precheck.py <file>", file=sys.stderr)
        return 2
    target = Path(sys.argv[1]).resolve()
    try:
        rel = target.relative_to(ROOT).as_posix()
    except ValueError:
        print("usage: the file must be inside the repo", file=sys.stderr)
        return 2
    if not target.is_file():
        print(f"usage: {rel} does not exist", file=sys.stderr)
        return 2

    blocks, notes = [], []

    # links.py prints "<file name> <link> missing file|missing anchor" for each broken link, by bare file name.
    _, out = run(str(CHECKS / "links.py"), ".")
    for line in out:
        if line.strip().split(" ", 1)[0] == target.name:
            blocks.append(f"links: {line.strip()}")

    # contracts.py prints "<module key> | depends on N.name | reason". Only module files are covered.
    m = re.match(r"docs/design/modules/(\w+?)-", rel)
    if m:
        key = m.group(1).upper().lstrip("0")
        _, out = run(str(CHECKS / "contracts.py"), ".")
        for line in out:
            if line.startswith(f"{key} | ") and "dashboard_url" not in line:  # known, documented non-gap
                blocks.append(f"contracts: {line.strip()}")

    # criteria.py: a criterion left open with a reason is allowed (AGENTS.md); only a tick with no test path,
    # or an open one with no reason, is a mechanical fault. It matches by prefix, so read only this file's line.
    if m:
        _, out = run(str(CHECKS / "criteria.py"), ".")
        for line in out:
            if line.startswith(target.name + ":"):
                n = [int(x) for x in re.findall(r"(\d+) (?:ticked without a test path|open without a reason)", line)]
                if any(n):
                    blocks.append(f"criteria: {line.strip()}")

    # records.py is about the whole repo; it names a file only when the problem is about that file.
    _, out = run(str(CHECKS / "records.py"), ".")
    for line in out:
        if line.startswith("records: ") and "problem(s)" not in line:
            (blocks if target.name in line else notes).append(f"records: {line[9:].strip()}")

    if blocks:
        print(f"BLOCKED: {rel} has mechanical failures. Fix them and run again. No scorecard.")
        for b in blocks:
            print("  " + b)
        for n in notes:
            print("  note (elsewhere in the repo, does not block): " + n)
        return 1
    print(f"OK: {rel} may be scored.")
    for n in notes:
        print("  note (elsewhere in the repo, does not block): " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
