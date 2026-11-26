#!/bin/sh
# Reproduce gate. Exit 0 while the bug reproduces (the repro test fails); exit 1 once it no longer does.
cd "$(dirname "$0")/.." || exit 2
PYTHONPATH=services/api PYTHONDONTWRITEBYTECODE=1 "${PYTHON:-python3}" -m pytest -q -p no:cacheprovider \
  "services/api/tests/test_report.py::test_total_counts_every_row" >/dev/null 2>&1
[ $? -eq 1 ]
