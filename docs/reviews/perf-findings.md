# Performance findings

A record for a later retrospective. One row per finding. Nothing here is acted on yet.

**How to use it.** Add a row when you find a way to speed up the test suite or a factory run. Say how you know it in the Evidence column, using one of three words:

- **measured**: you timed it. Keep the raw output in `docs/reviews/perf/` and name the file in the row.
- **read**: you saw it in the code or counted it, but did not time it.
- **guess**: you think it is true and have not checked.

Change a row's Status when you measure it or act on it, and name the commit or task. Do not delete a row that turned out wrong. Mark it `wrong` and say why, so the retrospective can see what the guesses cost.

**Status** is one of `open`, `measured`, `acted on` or `wrong`.

## Findings

| ID | Date | Area | Finding | Evidence | Reproduce | Status | Link |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PF-1 | 2026-11-17 | suite | The full engine suite takes about 18 minutes: 859 passed, 2 skipped in 1079.97 s. | measured: `perf/full-suite-run2.log` (the run `docs/tasks.md` dates to module 16 part 2, on the code before `579dad2`'s annotation fix; the log holds dots only, no per-test times) | `cd factory/engine && .venv/bin/python -m pytest -q` | measured | none |
| PF-2 | 2026-11-17 | suite | The suite runs one test at a time on a 10-core machine, and `pytest-xdist` is not installed. Running it in parallel is the likeliest large gain. | read: `sysctl -n hw.ncpu` gave 10; `import xdist` fails in `factory/engine/.venv`. No parallel run was timed. | `sysctl -n hw.ncpu`; `.venv/bin/python -c "import xdist"` | open | none |
| PF-3 | 2026-11-17 | suite | Before a parallel run, check that each test has its own state. `FACTORY_HOME` is set per test in the `workers`, `decisions`, `delivery` and `engine` fixtures. Not checked for the `gitops`, `kit`, `skills`, `state`, `drivers` and `gates` folders. | read: `rg FACTORY_HOME tests/*/conftest.py` | `rg -n "FACTORY_HOME" factory/engine/tests` | open | none |
| PF-4 | 2026-11-17 | suite | `tests/workers` (128 tests) and `tests/gitops` (45 tests) hold most of the subprocess work: 109 and 104 subprocess, git or `srt` references by grep. Those two folders are the likely time cost. | read: counts by grep, not timed | `rg -c "subprocess\|gitops\.\|git\(\|srt" factory/engine/tests/<folder>` | open | none |
| PF-5 | 2026-11-17 | suite | The `time.sleep` calls in the tests are probably not the cost, because most are 600 s sleeps that a short timeout kills. | guess | none | open | none |
| PF-6 | 2026-11-17 | suite | `tests/drivers` took 10 min 48 s for 42 tests in the module 16 part 3 run. It is the only per-folder time recorded, so it is not known to be the slowest folder. | measured: `docs/tasks.md` Log entry for module 16 part 3 (log was `/private/tmp/m16-drivers-run.log`, not copied here) | `.venv/bin/python -m pytest -q tests/drivers` | measured | none |
| PF-7 | 2026-11-17 | fixture | `seed_repo` in `tests/drivers/cli_fixtures.py` copies the whole kit with `cp -R` for every driver test, then deletes `engine`, `.venv`, `__pycache__` and `tests`. The kit folder is 31 MB, 13 MB of it the `.venv`. The copy runs before the delete. | read: `du -sh factory`, fixture source. Not timed. | `du -sh factory factory/engine/.venv` | open | none |
| PF-8 | 2026-11-17 | factory run | `Engine._supervise` (`engine.py`, about lines 540 to 560) waits for every task in a batch before it starts a task that became ready. A task whose dependency finished early waits for the slowest sibling. The shipped `bug-fix` has little uneven work to gain from, because `backend`, `frontend` and `verify` are chained by `needs`. | read: code only. No real run was timed. | read `Engine._supervise` and `Engine._execute_tasks` | open | none |
| PF-9 | 2026-11-17 | suite | The suite's slowest tests are unknown. | guess | `.venv/bin/python -m pytest -q --durations=30` | open | none |

## Next measurements

1. Run the suite with `--durations=30` once, to settle PF-4, PF-5, PF-6 and PF-9.
2. Install `pytest-xdist` in a scratch environment, not in `pyproject.toml`, and time `-n 4` and `-n 8`. A failure that shows up only in parallel settles PF-3.
3. Time `seed_repo` alone, to settle PF-7.

Adding `pytest-xdist` to the dev group changes `pyproject.toml` and `uv.lock`. Do that in its own commit, after PF-2 and PF-3 are measured.
