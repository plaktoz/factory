from __future__ import annotations

from dataclasses import dataclass, field

STANDARDS = """# Ledger

A small bookkeeping library. Standards every change must follow:

1. Money is `decimal.Decimal`, never `float`.
2. No bare `except:` and no `except Exception` that swallows the error. Handle it or re-raise.
3. Library code under `ledger/` never calls `print`. Use `logging`.
4. Every public function has type hints and a docstring.
5. No credentials or tokens in source. Read them from the environment.
6. Every new public function has a test in `tests/`.
7. SQL takes parameters. Never build it with string formatting.
"""

BASE: dict[str, str] = {
    "AGENTS.md": STANDARDS,
    "ledger/__init__.py": '"""Ledger."""\n',
    "ledger/amounts.py": '''"""Money arithmetic for the ledger."""
from decimal import Decimal


def add(a: Decimal, b: Decimal) -> Decimal:
    """Return the sum of two amounts."""
    return a + b


def total(amounts: list[Decimal]) -> Decimal:
    """Return the sum of all amounts, zero for none."""
    result = Decimal("0")
    for amount in amounts:
        result = add(result, amount)
    return result
''',
    "ledger/store.py": '''"""Reads and writes ledger rows."""
import sqlite3
from decimal import Decimal


def find_entries(conn: sqlite3.Connection, account: str) -> list[tuple[str, Decimal]]:
    """Return (memo, amount) rows for an account."""
    rows = conn.execute("SELECT memo, amount FROM entries WHERE account = ?", (account,)).fetchall()
    return [(memo, Decimal(amount)) for memo, amount in rows]


def add_entry(conn: sqlite3.Connection, account: str, memo: str, amount: Decimal) -> None:
    """Insert one entry."""
    conn.execute("INSERT INTO entries (account, memo, amount) VALUES (?, ?, ?)", (account, memo, str(amount)))
''',
    "ledger/report.py": '''"""Text report for an account."""
import logging
import sqlite3
from decimal import Decimal

from ledger.store import find_entries

log = logging.getLogger(__name__)


def render(conn: sqlite3.Connection, account: str) -> str:
    """Return one line per entry and a total line."""
    entries = find_entries(conn, account)
    lines = [f"{memo}: {amount}" for memo, amount in entries]
    total = sum((amount for _, amount in entries), Decimal("0"))
    lines.append(f"total: {total}")
    log.info("rendered %d entries for %s", len(entries), account)
    return "\\n".join(lines)
''',
    "ledger/archive.py": '''"""Headers for the archive service."""
import os


def archive_headers() -> dict[str, str]:
    """Return the request headers, with the token read from the environment."""
    return {"Authorization": "Bearer " + os.environ["LEDGER_ARCHIVE_TOKEN"]}
''',
    "tests/test_amounts.py": '''from decimal import Decimal

from ledger.amounts import add, total


def test_add():
    assert add(Decimal("1.10"), Decimal("2.20")) == Decimal("3.30")


def test_total():
    assert total([Decimal("1"), Decimal("2")]) == Decimal("3")
    assert total([]) == Decimal("0")
''',
    "tests/test_archive.py": '''import pytest

from ledger.archive import archive_headers


def test_headers(monkeypatch):
    monkeypatch.setenv("LEDGER_ARCHIVE_TOKEN", "abc")
    assert archive_headers() == {"Authorization": "Bearer abc"}
''',
    "tests/test_store.py": '''import sqlite3
from decimal import Decimal

from ledger.store import add_entry, find_entries


def make() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE entries (account TEXT, memo TEXT, amount TEXT)")
    return conn


def test_round_trip():
    conn = make()
    add_entry(conn, "cash", "coffee", Decimal("2.50"))
    assert find_entries(conn, "cash") == [("coffee", Decimal("2.50"))]
''',
}


@dataclass
class Case:
    id: str
    title: str
    edits: list[tuple[str, str, str]]
    new_files: dict[str, str] = field(default_factory=dict)
    planted: tuple[str, str] | None = None
    note: str = ""

    @property
    def changed(self) -> list[str]:
        return sorted({p for p, _, _ in self.edits} | set(self.new_files))

    def files(self) -> dict[str, str]:
        out = dict(BASE)
        for path, old, new in self.edits:
            if old:
                assert old in out[path], f"{self.id}: {old!r} not in {path}"
                out[path] = out[path].replace(old, new, 1)
            else:
                out[path] += new
        out.update(self.new_files)
        return out

    def planted_line(self) -> int | None:
        if self.planted is None:
            return None
        path, marker = self.planted
        for n, line in enumerate(self.files()[path].splitlines(), 1):
            if marker in line:
                return n
        raise AssertionError(f"{self.id}: marker {marker!r} not in {path}")


CASES: list[Case] = [
    Case("p1-float-money", "Return the total as a float for the report",
         [("ledger/amounts.py",
           'def total(amounts: list[Decimal]) -> Decimal:\n    """Return the sum of all amounts, zero for none."""\n'
           '    result = Decimal("0")\n    for amount in amounts:\n        result = add(result, amount)\n    return result\n',
           'def total(amounts: list[Decimal]) -> float:\n    """Return the sum of all amounts, zero for none."""\n'
           '    return float(sum(amounts))\n')],
         planted=("ledger/amounts.py", "return float(sum")),
    Case("p2-swallowed-error", "Make add_entry tolerate a locked database",
         [("ledger/store.py",
           '    conn.execute("INSERT INTO entries (account, memo, amount) VALUES (?, ?, ?)", (account, memo, str(amount)))\n',
           '    try:\n        conn.execute("INSERT INTO entries (account, memo, amount) VALUES (?, ?, ?)",\n'
           '                     (account, memo, str(amount)))\n    except Exception:\n        pass\n')],
         planted=("ledger/store.py", "except Exception:")),
    Case("p3-print-in-library", "Show progress while rendering a report",
         [("ledger/report.py", '    log.info("rendered %d entries for %s", len(entries), account)\n',
           '    print("rendered", len(entries), "entries for", account)\n')],
         planted=("ledger/report.py", "print(")),
    Case("p4-hardcoded-token", "Send the archive token from a constant",
         [("ledger/archive.py",
           'import os\n\n\ndef archive_headers() -> dict[str, str]:\n    """Return the request headers, with the token read from the environment."""\n'
           '    return {"Authorization": "Bearer " + os.environ["LEDGER_ARCHIVE_TOKEN"]}\n',
           'TOKEN = "example-placeholder-not-a-real-token"\n\n\ndef archive_headers() -> dict[str, str]:\n    """Return the request headers."""\n'
           '    return {"Authorization": "Bearer " + TOKEN}\n')],
         planted=("ledger/archive.py", 'TOKEN = "')),
    Case("p5-sql-format", "Look up entries by account name",
         [("ledger/store.py",
           '    rows = conn.execute("SELECT memo, amount FROM entries WHERE account = ?", (account,)).fetchall()\n',
           '    rows = conn.execute(f"SELECT memo, amount FROM entries WHERE account = \'{account}\'").fetchall()\n')],
         planted=("ledger/store.py", 'f"SELECT')),
    Case("p6-untested-function", "Add an average helper",
         [("ledger/amounts.py", "",
           '\n\ndef average(amounts: list[Decimal]) -> Decimal:\n    """Return the mean of the amounts."""\n'
           '    return total(amounts) / len(amounts)\n')],
         planted=("ledger/amounts.py", "def average")),
    Case("c1-subtract-with-test", "Add a subtract helper",
         [("ledger/amounts.py", "",
           '\n\ndef subtract(a: Decimal, b: Decimal) -> Decimal:\n    """Return a minus b."""\n    return a - b\n'),
          ("tests/test_amounts.py", "from ledger.amounts import add, total", "from ledger.amounts import add, subtract, total"),
          ("tests/test_amounts.py", "",
           '\n\ndef test_subtract():\n    assert subtract(Decimal("3"), Decimal("1")) == Decimal("2")\n')]),
    Case("c2-simplify-total", "Simplify total",
         [("ledger/amounts.py",
           '    result = Decimal("0")\n    for amount in amounts:\n        result = add(result, amount)\n    return result\n',
           '    return sum(amounts, Decimal("0"))\n')]),
    Case("c3-log-count", "Log the account when a report has no entries",
         [("ledger/report.py", '    lines = [f"{memo}: {amount}" for memo, amount in entries]\n',
           '    if not entries:\n        log.warning("no entries for %s", account)\n'
           '    lines = [f"{memo}: {amount}" for memo, amount in entries]\n')]),
    Case("c4-limit-parameter", "Let callers limit the number of entries",
         [("ledger/store.py",
           'def find_entries(conn: sqlite3.Connection, account: str) -> list[tuple[str, Decimal]]:\n    """Return (memo, amount) rows for an account."""\n'
           '    rows = conn.execute("SELECT memo, amount FROM entries WHERE account = ?", (account,)).fetchall()\n',
           'def find_entries(conn: sqlite3.Connection, account: str, limit: int = 100) -> list[tuple[str, Decimal]]:\n'
           '    """Return up to `limit` (memo, amount) rows for an account."""\n'
           '    rows = conn.execute("SELECT memo, amount FROM entries WHERE account = ? LIMIT ?", (account, limit)).fetchall()\n')],
         note="decoy: a changed SQL line, still parameterized"),
    Case("c5-print-in-test", "Show the stored row in a test",
         [("tests/test_store.py", '    assert find_entries(conn, "cash") == [("coffee", Decimal("2.50"))]\n',
           '    rows = find_entries(conn, "cash")\n    print(rows)\n    assert rows == [("coffee", Decimal("2.50"))]\n')],
         note="decoy: print, but outside ledger/, which standard 3 does not cover"),
    Case("c6-clear-missing-token", "Fail clearly when the archive token is not set",
         [("ledger/archive.py",
           '    return {"Authorization": "Bearer " + os.environ["LEDGER_ARCHIVE_TOKEN"]}\n',
           '    try:\n        token = os.environ["LEDGER_ARCHIVE_TOKEN"]\n    except KeyError as e:\n'
           '        raise RuntimeError("LEDGER_ARCHIVE_TOKEN is not set") from e\n    return {"Authorization": "Bearer " + token}\n'),
          ("tests/test_archive.py", "",
           '\n\ndef test_missing_token(monkeypatch):\n    monkeypatch.delenv("LEDGER_ARCHIVE_TOKEN", raising=False)\n'
           '    with pytest.raises(RuntimeError):\n        archive_headers()\n')],
         note="decoy: an except block that re-raises, with a test for the new path"),
]
