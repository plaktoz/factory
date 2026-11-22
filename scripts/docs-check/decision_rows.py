"""A `Decisions` row must give its Why and its Not chosen, never a placeholder (AGENTS.md, Working rules).

The fold of 2026-11-22 turned the reasons it did not carry over into the text "Not recorded in the ADR". The reasons
were still in git, so a later reader was told that nothing was written when it had only not been looked up. A row now
states its reason, or states that the source has none ("None recorded: ..."), which a person chose to write.

`placeholder_problems` is pure: it takes a file's text and returns one problem per bad row.
"""
from __future__ import annotations

import re

HEADER = re.compile(r"^\|\s*Rule\s*\|\s*Why\s*\|\s*Not chosen\s*\|\s*Id\s*\|\s*$")
PLACEHOLDER = re.compile(r"not recorded in the adr|no other reason is recorded|\btbd\b|\btodo\b|^\s*[-–—]?\s*$", re.I)


def placeholder_problems(name: str, text: str) -> list[str]:
    """One problem per Decisions-table row whose Why or Not chosen cell is empty or a placeholder."""
    problems, in_table = [], False
    for n, line in enumerate(text.split("\n"), 1):
        if HEADER.match(line):
            in_table = True
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if not in_table or set(line) <= set("|- :") or len(cells) < 4:
            continue
        for label, cell in (("Why", cells[-3]), ("Not chosen", cells[-2])):
            if PLACEHOLDER.search(cell):
                problems.append(f"{name}:{n}: the {label} cell is {cell[:40]!r}; read the source the Id names "
                                f"(git history if the file was deleted) and write the reason, or write "
                                f"'None recorded: <what the source says>'")
    return problems
