from report import build_report, report_total

ROWS = [{"amount_cents": 1250}, {"amount_cents": 300}, {"amount_cents": 49}]


def test_total_counts_every_row():
    assert report_total(ROWS) == 1599


def test_total_of_no_rows_is_zero():
    assert report_total([]) == 0


def test_report_carries_the_row_count():
    assert build_report(ROWS)["count"] == 3
