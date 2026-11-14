"""Read the function and method signatures that the spec's python blocks declare.

The spec writes a signature on one or more lines, often with no body and with a docstring or a comment after it:

    def load_config(repo: Path | None, *, env: Mapping[str, str] = os.environ) -> Config
        \"\"\"Merge defaults ...\"\"\"

A block names the file it belongs to with a comment line such as `# gitops.py` or `# adapters/tracker/base.py`.
A signature belongs to the last such comment above it in the same block. Methods of a class are keyed `Class.method`.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from spec_blocks import REPO

SPEC_DIRS = [REPO / "docs/design/modules", REPO / "docs/design/shared"]
FILE_COMMENT = re.compile(r"^#\s+((?:[a-z_]+/)*[a-z_0-9]+\.py)\b")


@dataclass(frozen=True)
class Param:
    name: str
    kind: str          # positional, keyword_only, var_positional, var_keyword
    has_default: bool
    annotation: str | None


@dataclass(frozen=True)
class Sig:
    key: str           # "load_config" or "Clock.now"
    file: str | None   # "config.py" or None when the block names no file
    spec: str          # which spec file, for messages
    params: tuple[Param, ...]
    returns: str | None


def _balanced(text: str) -> bool:
    return text.count("(") == text.count(")") and text.count("[") == text.count("]")


def _parse_def(source: str) -> ast.FunctionDef | None:
    # The spec ends a signature in different ways: nothing, `:`, or `: ...`. Take all three.
    source = re.sub(r":\s*(?:\.\.\.)?\s*$", "", source.strip())
    try:
        return ast.parse(f"{source}: ...").body[0]  # type: ignore[return-value]
    except SyntaxError:
        return None


def _params(fn: ast.FunctionDef) -> tuple[Param, ...]:
    a = fn.args
    out: list[Param] = []
    pos = a.posonlyargs + a.args
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    for arg, d in zip(pos, defaults):
        if arg.arg in ("self", "cls"):
            continue
        out.append(Param(arg.arg, "positional", d is not None, ast.unparse(arg.annotation) if arg.annotation else None))
    if a.vararg:
        out.append(Param(a.vararg.arg, "var_positional", False, None))
    for arg, d in zip(a.kwonlyargs, a.kw_defaults):
        out.append(Param(arg.arg, "keyword_only", d is not None, ast.unparse(arg.annotation) if arg.annotation else None))
    if a.kwarg:
        out.append(Param(a.kwarg.arg, "var_keyword", False, None))
    return tuple(out)


def _split_inline(line: str) -> list[str]:
    """Two or more `def`s on one line, separated by `;` (module 16 writes `def goto(...); def skip(...)`)."""
    parts, depth, cur = [], 0, ""
    for ch in line:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == ";" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def _strip_comment(text: str) -> str:
    """Remove a trailing `# ...`. A `#` outside quotes starts a comment, whatever the bracket depth: a signature
    that continues on the next line still has its brackets open at the end of the first one."""
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#":
            return text[:i]
    return text


def block_signatures(block: str, spec: str) -> list[Sig]:
    lines = block.split("\n")
    sigs: list[Sig] = []
    file: str | None = None
    cls: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        m = FILE_COMMENT.match(line)
        if m:
            file, cls = m.group(1), None
        cm = re.match(r"class (\w+)", line)
        if cm:
            cls = cm.group(1)
        elif line and not line[0].isspace() and not line.startswith(("def ", "#", "@")) and cls:
            cls = None
        pieces = _split_inline(_strip_comment(line))
        last = i
        for n, piece in enumerate(pieces):
            dm = re.match(r"(\s*)(?:async )?def (\w+)\(", line if n == 0 else piece)
            if not dm:
                continue
            text = (pieces[0] if len(pieces) > 1 else _strip_comment(line)) if n == 0 else piece
            j = i
            # a signature may run over the next lines until its brackets balance; comments are dropped first
            while not _balanced(text) and j + 1 < len(lines):
                j += 1
                text += " " + _strip_comment(lines[j]).strip()
            last = max(last, j)
            fn = _parse_def(text)
            if fn is not None:
                indent = len(dm.group(1))
                owner = cls if indent > 0 and cls else None
                key = f"{owner}.{fn.name}" if owner else fn.name
                sigs.append(Sig(key, file, spec, _params(fn), ast.unparse(fn.returns) if fn.returns else None))
        i = last + 1
    return sigs


def spec_signatures() -> list[Sig]:
    out: list[Sig] = []
    for d in SPEC_DIRS:
        for p in sorted(d.glob("*.md")):
            for block in re.findall(r"```python\n(.*?)```", p.read_text(), re.S):
                out.extend(block_signatures(block, p.name))
    return out
