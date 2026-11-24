"""Module 11, every stop kind: a run that the engine blocks writes a decision file that offers retry, goto, skip and abort (module 8,
"When a run is blocked, its decision file offers these options"). The engine template for the blocked kind is tested in
tests/decisions/test_decisions.py, but a real block never calls it, so no file is written. This test is strict xfail
until the engine writes the file on a block: when it starts passing, remove the marker."""

import pytest

from factory_engine import decisions as D
from factory_engine import state

from test_max_interruptions import _chore, _cut_off_n_times


@pytest.mark.xfail(strict=True, reason="the engine sets the blocked attention item (rework._blocked) and writes no decision file for it; "
                                       "module 8 says it does")
def test_a_run_the_engine_blocks_writes_a_decision_file_with_the_four_blocked_options(new_run, engine):
    run_dir, eng, _ = _chore(new_run, engine, attempts=4)
    _cut_off_n_times(eng, "bump-q1w2e", 3)
    eng.resume("bump-q1w2e")
    run = state.read_run(run_dir)
    assert run.status == "blocked"
    doc = D.read_decision(run_dir, run.stage, D.latest_visit(run, run.stage))
    assert {o["id"] for o in doc["packet"]["decisions"][0]["options"]} == D.BLOCKED_OPTIONS
