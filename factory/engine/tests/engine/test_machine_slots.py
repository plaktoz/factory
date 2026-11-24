"""Module 3 `max_workers`: the slot files cap workers across engine processes (`factory_engine/slots.py`)."""

import subprocess
import sys
import textwrap

from factory_engine import slots

HOLD = textwrap.dedent("""
    import sys, time
    from pathlib import Path
    from factory_engine import slots
    held = slots.acquire(Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]))
    print("held" if held else "none", flush=True)
    time.sleep(60)
""")


def _hold(home, limit, count):
    """A separate process that takes `count` slots and keeps them until killed. Returns it once it has answered."""
    p = subprocess.Popen([sys.executable, "-c", HOLD, str(home), str(limit), str(count)],
                         stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held"
    return p


def test_slots_held_by_another_process_count_against_the_limit(tmp_path):
    other = _hold(tmp_path, 6, 5)
    try:
        mine = slots.acquire(tmp_path, 6, 1)
        assert mine is not None                       # the sixth slot is free
        assert slots.acquire(tmp_path, 6, 1) is None  # a seventh worker waits, though it is another process
        slots.release_all(mine)
        assert slots.acquire(tmp_path, 6, 1) is not None
    finally:
        other.kill()
        other.wait()


def test_a_killed_engine_frees_its_slots(tmp_path):
    other = _hold(tmp_path, 2, 2)
    assert slots.acquire(tmp_path, 2, 1) is None
    other.kill()
    other.wait()
    held = slots.acquire(tmp_path, 2, 2)
    assert held is not None and len(held) == 2        # no stale count to clear by hand
    slots.release_all(held)


def test_a_task_takes_all_its_slots_or_none(tmp_path):
    held = slots.acquire(tmp_path, 3, 2)
    assert held is not None
    assert slots.acquire(tmp_path, 3, 2) is None      # one is free, two are asked for: it takes neither
    one = slots.acquire(tmp_path, 3, 1)               # so the free one is still free
    assert one is not None
    slots.release_all(held + one)


def test_a_cap_of_zero_starts_no_worker(tmp_path):
    """A cap of 0 must refuse, not read as no cap: `Engine._take_slots` returns None before it takes any slot."""
    from types import SimpleNamespace

    from factory_engine.engine import Engine
    eng = SimpleNamespace(home=tmp_path, key="k", _concurrency=lambda: 4, _max_workers=lambda: 0)
    assert Engine._take_slots(eng, 1) is None
    eng = SimpleNamespace(home=tmp_path, key="k", _concurrency=lambda: 0, _max_workers=lambda: 6)
    assert Engine._take_slots(eng, 1) is None
