"""decision_rows.py: a Decisions row with a placeholder reason is a problem. Run: python3 -m pytest scripts/docs-check/test_decision_rows.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decision_rows import placeholder_problems  # noqa: E402

HEAD = "## Decisions\n\n| Rule | Why | Not chosen | Id |\n| --- | --- | --- | --- |\n"


def table(*rows):
    return HEAD + "\n".join(rows) + "\n"


def test_the_placeholder_the_fold_wrote_is_reported_in_either_cell():
    text = table("| Use an OS lock. | Not recorded in the ADR. | Not recorded in the ADR. | 2026-11-14-x (D1) |")
    problems = placeholder_problems("m6.md", text)
    assert len(problems) == 2 and "m6.md:5" in problems[0] and "Why" in problems[0] and "Not chosen" in problems[1]


def test_the_old_no_reason_wording_and_an_empty_cell_are_reported():
    text = table("| A. | The owner chose this. No other reason is recorded. | B. | id-a |", "| C. |  | D. | id-b |")
    assert len(placeholder_problems("m.md", text)) == 2


def test_a_row_with_reasons_and_a_deliberate_none_recorded_passes():
    text = table("| A. | It is simpler. | B, which is slower. | id-a |",
                 "| C. | A check that reports passed false must not pass. | None recorded: the option list is not in the repo. | id-b |")
    assert placeholder_problems("m.md", text) == []


def test_text_outside_a_decisions_table_is_not_read():
    assert placeholder_problems("m.md", "The ADR said Not recorded in the ADR in prose.\n\n| a | b | c | d |\n| - | - | - | - |\n| 1 | TBD | 3 | 4 |\n") == []
