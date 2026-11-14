"""Read the python code blocks of the spec and return {class name: [field names]}.

The spec writes dataclasses in a compact style: several `name: type` fields on one line, separated by `;`,
and continuation lines indented under the class line. Types may contain `;` only inside brackets (none do).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SPEC_FILES = [
    REPO / "docs/design/shared/18-shared-contracts.md",
    REPO / "docs/design/modules/05-workflows-and-plugins.md",
]


def _split_top_level(text: str, sep: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def dataclass_fields(path: Path) -> dict[str, list[str]]:
    text = path.read_text()
    out: dict[str, list[str]] = {}
    for block in re.findall(r"```python\n(.*?)```", text, re.S):
        lines = block.split("\n")
        i = 0
        while i < len(lines):
            m = re.match(r"class (\w+)(\(.*?\))?:\s*(.*)$", lines[i])
            if not m or (m.group(2) and "Protocol" in m.group(2)) or (m.group(2) and "Exception" in m.group(2)):
                i += 1
                continue
            name, rest = m.group(1), m.group(3)
            body = rest
            j = i + 1
            # continuation lines: indented, not blank, not a new statement
            while j < len(lines) and lines[j].startswith(" ") and lines[j].strip() and not lines[j].lstrip().startswith(("def ", "class ", '"""')):
                body += ";" + lines[j].strip()
                j += 1
            body = re.sub(r"#.*", "", body)
            fields = []
            for piece in _split_top_level(body, ";"):
                piece = piece.strip()
                fm = re.match(r"(\w+)\s*:\s*\S", piece)
                if fm:
                    fields.append(fm.group(1))
            if fields:
                out.setdefault(name, fields)
            i = j
    return out


def spec_fields() -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for p in SPEC_FILES:
        for k, v in dataclass_fields(p).items():
            merged.setdefault(k, v)
    return merged
