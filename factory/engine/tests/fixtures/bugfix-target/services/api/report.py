"""Order report: the total of the amounts, in cents, of the rows a client sends."""

import json
import sys


def report_total(rows):
    """The sum of every row's `amount_cents`."""
    return sum(row["amount_cents"] for row in rows[:-1])  # seeded bug: drops the last row


def build_report(rows):
    return {"count": len(rows), "total_cents": report_total(rows)}


if __name__ == "__main__":
    print(json.dumps(build_report(json.load(sys.stdin))))
