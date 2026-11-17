"""The repo engine's CLI (module 16): every run command exists, prints the shared JSON shape, and uses the shared exit codes.

Each test drives `cli.main()` with the fakes injected, so no engine process and no worker starts. The spawn is replaced
with a recorder: a test asks whether an engine would have started, and the answer is the proof for the criterion.
"""

import json
from pathlib import Path

import pytest

from cli_fixtures import seed_repo
from engine_fixtures import chore_script  # noqa: F401  (keeps the engine fixtures on the path)

from factory_engine import api, cli, state
from factory_engine.adapters.tracker.fake import FakeTracker
from factory_engine.adapters.worker.fake import FakeWorkerAdapter, failed
from factory_engine.errors import EXIT_BLOCKED, EXIT_INVALID, EXIT_LOCKED, EXIT_OK, EXIT_WAITING_HUMAN
from factory_engine.fake_prs import FakePullRequests
from factory_engine.lock import acquire_lock, release
from factory_engine import skills

KIT = Path(__file__).resolve().parents[3]  # factory/
REAL_SPAWN = api.spawn_engine  # captured before the `spawned` fixture replaces it

# Every command the module 16 table names, and the handler that owns it. The test below checks each one parses.
RUN_COMMANDS = ["init", "upgrade", "doctor", "add", "sync", "run", "decide", "check", "reopen", "open", "note",
                "retry", "goto", "skip", "abort", "resume", "recover", "status", "where", "events", "usage", "gc"]


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FACTORY_WORKTREE_ROOT", str(tmp_path / "wt"))
    skills.use_kit(KIT)
    yield seed_repo(tmp_path)
    skills.use_kit(Path(skills.__file__).resolve().parents[2])


@pytest.fixture
def spawned(monkeypatch):
    """Records each engine the CLI would start. The real spawn would start a detached process."""
    calls: list[str] = []
    monkeypatch.setattr(api, "spawn_engine", lambda repo, run_id: calls.append(run_id) or 4242)
    return calls


def run_cli(argv, capsys, **factories):
    code = cli.main(argv, **factories)
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    return code, (json.loads(lines[-1]) if lines and lines[-1].startswith("{") else None)


def _add(seeded, capsys, spawned, title="Bump the lint config", *extra) -> str:
    code, doc = run_cli(["add", title, "--type", "chore", "--repo", str(seeded), "--json", *extra], capsys)
    assert code == EXIT_OK, doc
    return doc["data"]["run_id"]


def _factories(worker_script=None, writes=None):
    worker = FakeWorkerAdapter(worker_script or {}, writes=writes)
    return dict(worker_factory=lambda cfg: {"claude": worker}, tracker_factory=lambda repo, cfg: FakeTracker(),
                prs_factory=lambda repo, cfg: FakePullRequests())


# ---- every command exists and parses -----------------------------------------------------------------------------

def test_every_run_command_in_the_module_table_is_a_subcommand():
    parser = cli._parser()
    names = set(parser._subparsers._group_actions[0].choices)
    missing = [c for c in RUN_COMMANDS if c not in names]
    assert not missing, f"commands missing from the CLI: {missing}"


def test_misuse_exits_2_and_with_json_prints_the_shared_shape(capsys):
    code, doc = run_cli(["run", "--json"], capsys)
    assert code == EXIT_INVALID
    assert set(doc) == {"ok", "code", "message", "hint", "data"} and doc["ok"] is False


def test_an_argparse_error_with_json_still_prints_the_shared_shape(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["add", "--json"])
    assert e.value.code == EXIT_INVALID
    doc = json.loads(capsys.readouterr().out)
    assert set(doc) == {"ok", "code", "message", "hint", "data"} and doc["ok"] is False


def test_an_argparse_error_without_json_uses_argparse_text(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["add"])
    assert e.value.code == EXIT_INVALID
    assert "required" in capsys.readouterr().err


# ---- add, sync and run ------------------------------------------------------------------------------------------

def test_add_creates_a_run_and_prints_its_id_without_starting_an_engine_when_asked(seeded, capsys, spawned):
    code, doc = run_cli(["add", "Bump the lint config", "--type", "chore", "--repo", str(seeded), "--json", "--no-run"],
                        capsys)
    assert code == EXIT_OK and doc["ok"] is True and doc["data"]["run_id"]
    assert doc["data"]["started_pid"] is None and spawned == []


def test_add_starts_one_engine_unless_no_run_is_given(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    assert spawned == [run_id]


def test_sync_creates_runs_from_the_inbox_and_starts_no_engine(seeded, capsys, spawned):
    (seeded / ".factory" / "config").mkdir(parents=True, exist_ok=True)
    (seeded / ".factory" / "config" / "factory.yaml").write_text("base_branch: main\ntracker: file\nharness: claude\n")
    inbox = seeded / ".factory" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "request.md").write_text("---\ntype: chore\n---\n# Bump the lint config\n\nBump it.\n")
    code, doc = run_cli(["sync", "--repo", str(seeded), "--json"], capsys)
    assert code == EXIT_OK and len(doc["data"]["created"]) == 1
    assert spawned == []


def test_run_with_no_run_id_and_no_all_is_refused(seeded, capsys):
    code, doc = run_cli(["run", "--repo", str(seeded), "--json"], capsys)
    assert code == EXIT_INVALID and doc["ok"] is False


def test_run_drives_a_chore_run_to_done_and_exits_0(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned, "Bump the lint config")
    run_dir = state.find_run(state.factory_home(), run_id).run_dir
    script, writes = chore_script(run_dir)
    code, doc = run_cli(["run", run_id, "--repo", str(seeded), "--json"], capsys,
                        **_factories(script, writes))
    assert code == EXIT_OK and doc["data"]["runs"] == {run_id: "done"}


def test_run_exits_3_when_the_run_waits_for_a_human(seeded, capsys, spawned, monkeypatch):
    """A stage that needs approval parks the run as awaiting_approval, which the CLI reports as exit 3."""
    run_id = _add(seeded, capsys, spawned)
    run_dir = state.find_run(state.factory_home(), run_id).run_dir
    script, writes = chore_script(run_dir)
    wf_dir = seeded / ".factory" / "config" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "chore.yaml").write_text((KIT / "workflows" / "chore.yaml").read_text().replace(
        "    gate: [{check: scope-diff}, {check: lint-clean}]\n", "    gate: [{check: scope-diff}]\n    approval: human\n", 1))
    code, doc = run_cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **_factories(script, writes))
    assert code == EXIT_WAITING_HUMAN and doc["data"]["runs"] == {run_id: "awaiting_approval"}


def test_run_exits_4_when_the_run_is_blocked(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    run_dir = state.find_run(state.factory_home(), run_id).run_dir
    script, writes = chore_script(run_dir, change=[failed("crash")] * 3)
    code, doc = run_cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **_factories(script, writes))
    assert code == EXIT_BLOCKED and doc["data"]["runs"] == {run_id: "blocked"}
    assert "retry" in doc["hint"] or "status" in doc["hint"]


def test_run_detach_starts_an_engine_and_returns_its_pid(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned, "Bump the lint config", "--no-run")
    code, doc = run_cli(["run", run_id, "--repo", str(seeded), "--detach", "--json"], capsys)
    assert code == EXIT_OK and doc["data"]["started"] == {run_id: 4242}


# ---- decide, retry, goto and skip start an engine only when no live lock exists ----------------------------------

def _blocked_run(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    run_dir = state.find_run(state.factory_home(), run_id).run_dir
    script, writes = chore_script(run_dir, change=[failed("crash")] * 3)
    run_cli(["run", run_id, "--repo", str(seeded), "--json"], capsys, **_factories(script, writes))
    assert state.read_run(run_dir).status == "blocked"
    spawned.clear()
    return run_id, run_dir


def test_retry_starts_an_engine_when_no_live_lock_holds_the_run(seeded, capsys, spawned):
    run_id, _ = _blocked_run(seeded, capsys, spawned)
    code, doc = run_cli(["retry", run_id, "--repo", str(seeded), "--json"], capsys)
    assert code == EXIT_OK and doc["data"]["started_pid"] == 4242
    assert spawned == [run_id]


def test_goto_starts_an_engine_when_no_live_lock_holds_the_run(seeded, capsys, spawned):
    run_id, _ = _blocked_run(seeded, capsys, spawned)
    code, doc = run_cli(["goto", run_id, "implement", "--repo", str(seeded), "--json"], capsys)
    assert code == EXIT_OK and spawned == [run_id]


def test_skip_refuses_a_gate_not_marked_skippable_and_starts_nothing(seeded, capsys, spawned):
    run_id, _ = _blocked_run(seeded, capsys, spawned)
    code, doc = run_cli(["skip", run_id, "--gate", "lint-clean", "--reason", "flaky", "--repo", str(seeded), "--json"],
                        capsys)
    assert code == EXIT_INVALID and doc["ok"] is False and spawned == []


def test_retry_refuses_a_run_a_live_engine_holds(seeded, capsys, spawned):
    """The retry takes the run's lock first, so a live engine makes it exit 5 and start nothing."""
    run_id, run_dir = _blocked_run(seeded, capsys, spawned)
    holder = acquire_lock(run_dir, "another-engine")
    try:
        code, doc = run_cli(["retry", run_id, "--repo", str(seeded), "--json"], capsys)
    finally:
        release(holder)
    assert code == EXIT_LOCKED and doc["code"] == "state.locked" and doc["ok"] is False
    assert spawned == []


def test_spawn_engine_returns_none_while_a_live_lock_holds_the_run(seeded, capsys, spawned, monkeypatch):
    """The real spawn checks the lock before it starts anything, so a live engine means no second one."""
    run_id, run_dir = _blocked_run(seeded, capsys, spawned)
    holder = acquire_lock(run_dir, "another-engine")
    try:
        assert REAL_SPAWN(seeded, run_id) is None
    finally:
        release(holder)


def test_decide_refuses_a_stale_packet_with_exit_2(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned, "Bump the lint config", "--no-run")
    code, doc = run_cli(["decide", run_id, "--repo", str(seeded), "--json", "--packet", "not-the-sha", "D1=approve"],
                        capsys)
    assert code == EXIT_INVALID and doc["ok"] is False and spawned == []


# ---- decide takes its answers as trailing tokens, in any position (decision M1) -----------------------------------------

@pytest.fixture
def decide_calls(seeded, capsys, spawned, monkeypatch):
    """A run id to decide on, and a recorder for what the CLI hands to api.decide."""
    run_id = _add(seeded, capsys, spawned, "Bump the lint config", "--no-run")
    calls: list[dict] = []
    monkeypatch.setattr(cli, "_latest_stop_stage", lambda run_dir: "implement")
    monkeypatch.setattr(api, "decide", lambda repo, rid, stage, **kw: calls.append(kw) or _outcome("pending"))
    return run_id, calls


def _outcome(status):
    from factory_engine.decisions import Outcome
    return Outcome(status=status, choices={}, questions={}, notes="", code=None, message=None)


@pytest.mark.parametrize("order", [
    ["D1=opt-a", "D2=opt-b", "--notes", "n"],
    ["--notes", "n", "D1=opt-a", "D2=opt-b"],
    ["D1=opt-a", "--notes", "n", "D2=opt-b"],
], ids=["answers-first", "answers-last", "answers-between"])
def test_decide_reads_the_answers_wherever_they_sit_among_the_options(seeded, capsys, decide_calls, order):
    run_id, calls = decide_calls
    code, doc = run_cli(["decide", run_id, "--repo", str(seeded), "--json", "--packet", "661cb74d", *order], capsys)
    assert code == EXIT_OK, doc
    assert calls[0]["choices"] == {"D1": "opt-a", "D2": "opt-b"}
    assert calls[0]["notes"] == "n" and calls[0]["packet_sha"] == "661cb74d"


def test_decide_keeps_a_question_apart_from_the_answers(seeded, capsys, decide_calls):
    run_id, calls = decide_calls
    code, _ = run_cli(["decide", run_id, "--repo", str(seeded), "--json", "--packet", "661cb74d", "D1=opt-a",
                       "--question", "D2=Can option B add charts later?"], capsys)
    assert code == EXIT_OK
    assert calls[0]["choices"] == {"D1": "opt-a"} and calls[0]["questions"] == {"D2": "Can option B add charts later?"}


@pytest.mark.parametrize("stray", [["oops"], ["--choice", "D1=opt-a"], ["--chooice", "D1=opt-a"]])
def test_decide_rejects_a_token_that_is_not_an_answer_with_exit_2_and_asks_for_nothing(seeded, capsys, decide_calls, stray):
    run_id, calls = decide_calls
    with pytest.raises(SystemExit) as e:
        cli.main(["decide", run_id, "--repo", str(seeded), "--json", "--packet", "661cb74d", *stray])
    assert e.value.code == EXIT_INVALID and calls == []
    assert json.loads(capsys.readouterr().out)["code"] == "cli.usage"


def test_a_command_other_than_decide_still_rejects_a_stray_token(seeded, capsys, spawned):
    with pytest.raises(SystemExit) as e:
        cli.main(["sync", "D1=opt-a", "--repo", str(seeded), "--json"])
    assert e.value.code == EXIT_INVALID
    assert json.loads(capsys.readouterr().out)["code"] == "cli.usage"


# ---- init --github composes init_repo (3) with ensure_labels (7) ----------------------------------------------------

def test_init_github_creates_the_layout_and_the_factory_labels(tmp_path, capsys, monkeypatch):
    repo = tmp_path / "plain"
    repo.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    tracker = FakeTracker()
    code, doc = run_cli(["init", "--github", "--repo", str(repo), "--json"], capsys,
                        tracker_factory=lambda r, cfg: tracker)
    assert code == EXIT_OK
    assert (repo / ".factory" / "config" / "factory.yaml").is_file()
    assert "factory:queued" in tracker.labels and "factory" in tracker.labels
    assert "factory:queued" in doc["data"]["labels"]


def test_init_without_github_makes_no_tracker_call(tmp_path, capsys, monkeypatch):
    repo = tmp_path / "plain"
    repo.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    tracker = FakeTracker()
    code, _ = run_cli(["init", "--repo", str(repo), "--json"], capsys, tracker_factory=lambda r, cfg: tracker)
    assert code == EXIT_OK and tracker.labels == set()


# ---- the shared error shape --------------------------------------------------------------------------------------

def test_a_factory_error_prints_the_shared_shape_with_its_code(seeded, capsys, spawned):
    code, doc = run_cli(["status", "no-such-run", "--repo", str(seeded), "--json"], capsys)
    assert code == EXIT_INVALID
    assert set(doc) == {"ok", "code", "message", "hint", "data"} and doc["code"] == "config.invalid"
