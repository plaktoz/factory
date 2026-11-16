"""End to end through the CLI only: a seeded repo, `add`, then `run`, to a finished `chore` run.

The worker and the pull request service are the fakes, injected through the CLI's factories. Nothing calls the
engine's Python API. The run's state is read from its folder, which is what the CLI writes.

The bug-fix workflow is not used here. Its stages need a live repro script, make targets, JUnit reports, a helpers
ledger, a human approval stop and a review that writes findings. Seeding all of that in a test repo is a fixture of its
own, so the chore workflow, whose gates a seeded repo can meet, drives the path instead.
"""

import json
from pathlib import Path

import pytest

from engine_fixtures import chore_script  # noqa: E402

from cli_fixtures import KIT, seed_repo
from factory_engine import cli, skills, state
from factory_engine.adapters.worker.fake import FakeWorkerAdapter
from factory_engine.fake_prs import FakePullRequests


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FACTORY_WORKTREE_ROOT", str(tmp_path / "wt"))
    skills.use_kit(KIT)
    yield seed_repo(tmp_path)
    skills.use_kit(Path(skills.__file__).resolve().parents[2])


def _cli(argv: list[str], capsys, **factories) -> tuple[int, dict]:
    code = cli.main(argv, **factories)
    out = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(out[-1])


def test_a_chore_run_reaches_done_through_the_cli_alone(seeded, capsys, monkeypatch, tmp_path):
    spawned: list[str] = []
    monkeypatch.setattr(cli.api, "spawn_engine", lambda repo, run_id: spawned.append(run_id) or None)
    prs = FakePullRequests()

    code, added = _cli(["add", "Bump the lint config", "--type", "chore", "--repo", str(seeded), "--json", "--no-run"],
                       capsys)
    assert code == 0 and added["ok"] is True
    run_id = added["data"]["run_id"]

    run_dir = state.find_run(state.factory_home(), run_id).run_dir
    script, writes = chore_script(run_dir)
    worker = FakeWorkerAdapter(script, writes=writes)

    code, driven = _cli(["run", run_id, "--repo", str(seeded), "--json"], capsys,
                        worker_factory=lambda cfg: {"claude": worker},
                        tracker_factory=lambda repo, cfg: _tracker(),
                        prs_factory=lambda repo, cfg: prs)
    assert code == 0, driven
    assert driven["data"]["runs"] == {run_id: "done"}
    assert state.read_run(run_dir).status == "done"
    assert spawned == []  # `add --no-run` and `run` start no detached engine


def _tracker():
    from factory_engine.adapters.tracker.fake import FakeTracker
    return FakeTracker()
