"""The report from the API, piped through the page's formatter, prints the right line."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROWS = [{"amount_cents": 1250}, {"amount_cents": 300}, {"amount_cents": 49}]


def test_the_page_shows_the_full_total():
    api = subprocess.run([sys.executable, "services/api/report.py"], input=json.dumps(ROWS), text=True,
                         capture_output=True, check=True, cwd=ROOT, env={"PYTHONDONTWRITEBYTECODE": "1"})
    page = subprocess.run(["node", "web/format.js"], input=api.stdout, text=True, capture_output=True, check=True,
                          cwd=ROOT)
    assert page.stdout.strip() == "3 orders, $15.99"
