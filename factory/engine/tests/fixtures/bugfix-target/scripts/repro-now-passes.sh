#!/bin/sh
# Verify gate. Exit 0 when the repro test passes; non-zero while the bug is still there.
cd "$(dirname "$0")/.." || exit 2
PYTHONPATH=services/api PYTHONDONTWRITEBYTECODE=1 "${PYTHON:-python3}" -m pytest -q -p no:cacheprovider \
  "services/api/tests/test_report.py::test_total_counts_every_row"
