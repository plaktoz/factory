"""Module 16 acceptance: every command of the table exists, prints the shared `--json` shape, and exits with a shared code.

One row per command of the table, driven through `cli.main()` with fakes, so no worker, network or engine process
starts. The table is checked two ways: every row answers a bad flag with the shared shape and exit 2 (the parser),
and most rows have a success case and an error case of their own. Here `resume` has only its lock refusal, and
`retry`, `goto` and `skip` are tested in test_cli.py. `factory plugins enable|disable` has its own tests in
test_plugins_cli.py. The `factory` launcher's rows are in factory/launcher/tests/test_command_table.py.
"""

import json
import subprocess
from pathlib import Path

import pytest

from cli_fixtures import seed_repo
from engine_fixtures import chore_script  # noqa: F401  (keeps the engine fixtures on the path)

from factory_engine import api, cli, decisions, skills, state
from factory_engine.adapters.tracker.fake import FakeTracker
from factory_engine.adapters.worker.fake import FakeWorkerAdapter
from factory_engine.errors import EXIT_INVALID, EXIT_LOCKED, EXIT_OK, EXIT_FAILED
from factory_engine.fake_prs import FakePullRequests
from factory_engine.lock import acquire_lock, release
from factory_engine.types import TaskState

KIT = Path(__file__).resolve().parents[3]  # factory/
SHARED_CODES = {0, 1, 2, 3, 4, 5}
SHAPE = {"ok", "code", "message", "hint", "data"}

# Every command of the module 16 table that the repo engine runs (the launcher's machine rows are in its own test).
ENGINE_ROWS = ["init", "upgrade", "doctor", "add", "sync", "run", "decide", "check", "reopen", "open", "note",
               "retry", "goto", "skip", "abort", "resume", "recover", "status", "where", "events", "usage", "gc",
               "triage"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("FACTORY_HOME", str(h))
    monkeypatch.setenv("FACTORY_WORKTREE_ROOT", str(tmp_path / "wt"))
    return h


@pytest.fixture
def seeded(tmp_path, home):
    skills.use_kit(KIT)
    yield seed_repo(tmp_path)
    skills.use_kit(Path(skills.__file__).resolve().parents[2])


@pytest.fixture
def spawned(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(api, "spawn_engine", lambda repo, run_id: calls.append(run_id) or 4242)
    return calls


def run_cli(argv, capsys, **factories):
    """Run one command. Returns (exit code, the shared-shape document printed last, or None)."""
    code = cli.main(argv, **factories)
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    doc = json.loads(lines[-1]) if lines and lines[-1].startswith("{") else None
    return code, doc


def _add(seeded, capsys, spawned, *extra) -> str:
    code, doc = run_cli(["add", "Bump the lint config", "--type", "chore", "--repo", str(seeded), "--json",
                         "--no-run", *extra], capsys)
    assert code == EXIT_OK, doc
    return doc["data"]["run_id"]


def _run_dir(run_id: str) -> Path:
    return state.find_run(state.factory_home(), run_id).run_dir


def _factories():
    prs = FakePullRequests()
    return dict(worker_factory=lambda cfg: {"claude": FakeWorkerAdapter({})}, command_factory=lambda cfg: FakeWorkerAdapter({}),
                tracker_factory=lambda repo, cfg: FakeTracker(), prs_factory=lambda repo, cfg: prs)


def _assert_shared_shape(doc, code, *, ok):
    """A document in the shared shape, whose exit code is one of the shared codes."""
    assert doc is not None and set(doc) == SHAPE, doc
    assert doc["ok"] is ok and code in SHARED_CODES


# ---- the parser: every row answers a bad flag with the shared shape and exit 2 ---------------------------------------

@pytest.mark.parametrize("command", ENGINE_ROWS)
def test_every_row_answers_a_bad_flag_with_the_shared_shape_and_exit_2(command, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main([command, "--bogus-flag", "--json"])
    assert e.value.code == EXIT_INVALID
    doc = json.loads(capsys.readouterr().out)
    _assert_shared_shape(doc, e.value.code, ok=False)
    assert doc["code"] == "cli.usage"


def test_every_engine_row_is_a_subcommand():
    names = set(cli._parser()._subparsers._group_actions[0].choices)
    assert set(ENGINE_ROWS) <= names, sorted(set(ENGINE_ROWS) - names)


# ---- one success and one error case per row ---------------------------------------------------------------------------

def test_init_creates_the_kit_and_prints_the_shared_shape(tmp_path, home, capsys):
    repo = tmp_path / "plain"
    repo.mkdir()
    code, doc = run_cli(["init", "--repo", str(repo), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and (repo / ".factory" / "config" / "factory.yaml").is_file()


def test_init_outside_a_git_repo_with_no_repo_flag_is_a_config_error(tmp_path, home, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)  # not inside any git repo
    code, doc = run_cli(["init", "--json"], capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID and doc["code"] == "config.invalid"


def test_upgrade_replaces_the_kit_and_prints_the_shared_shape(tmp_path, home, capsys):
    repo = tmp_path / "plain"
    repo.mkdir()
    assert cli.main(["init", "--repo", str(repo), "--json"]) == EXIT_OK
    capsys.readouterr()
    code, doc = run_cli(["upgrade", "0.2.0", "--repo", str(repo), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"]["config_untouched"] is True


def test_upgrade_with_no_kit_folder_is_a_config_error(tmp_path, home, capsys):
    repo = tmp_path / "plain"
    repo.mkdir()
    code, doc = run_cli(["upgrade", "0.2.0", "--repo", str(repo), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID and doc["code"] == "config.invalid"


@pytest.mark.parametrize("ok, code_expected", [(True, EXIT_OK), (False, EXIT_FAILED)], ids=["all-pass", "one-fails"])
def test_doctor_exits_0_when_every_check_passes_and_1_when_one_fails(ok, code_expected, tmp_path, home, capsys,
                                                                    monkeypatch):
    from factory_engine.types import CheckResult
    monkeypatch.setattr(api, "doctor", lambda repo, as_scheduler=False: [
        CheckResult("git", True, "/usr/bin/git", ""), CheckResult("gh", ok, "", "" if ok else "run gh auth login")])
    code, doc = run_cli(["doctor", "--no-repo", "--json"], capsys)
    _assert_shared_shape(doc, code, ok=ok)
    assert code == code_expected


def test_add_creates_a_run_and_prints_the_shared_shape(seeded, capsys, spawned):
    code, doc = run_cli(["add", "Bump the lint config", "--type", "chore", "--repo", str(seeded), "--no-run", "--json"],
                        capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"]["run_id"]


def test_add_without_a_title_is_a_usage_error(seeded, capsys, spawned):
    """argparse exits 2 through SystemExit before any handler runs; with --json the shared shape is on stdout."""
    with pytest.raises(SystemExit) as e:
        cli.main(["add", "--repo", str(seeded), "--json"])
    doc = json.loads(capsys.readouterr().out)
    _assert_shared_shape(doc, e.value.code, ok=False)
    assert e.value.code == EXIT_INVALID and doc["code"] == "cli.usage"


def test_sync_reads_the_inbox_and_prints_the_shared_shape(seeded, capsys, spawned):
    (seeded / ".factory" / "config").mkdir(parents=True, exist_ok=True)
    (seeded / ".factory" / "config" / "factory.yaml").write_text("base_branch: main\ntracker: file\nharness: claude\n")
    inbox = seeded / ".factory" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "request.md").write_text("---\ntype: chore\n---\n# Bump the lint config\n\nBump it.\n")
    code, doc = run_cli(["sync", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and len(doc["data"]["created"]) == 1 and spawned == []


def test_run_with_no_run_id_and_no_all_is_a_usage_error(seeded, capsys, spawned):
    code, doc = run_cli(["run", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID


def test_run_all_detach_starts_each_run_and_prints_the_shared_shape(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    code, doc = run_cli(["run", "--all", "--detach", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"]["started"] == {run_id: 4242}


def test_decide_with_a_stale_packet_is_refused_with_exit_2(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    decisions.request(_run_dir(run_id), "propose", 1, kind="approval")
    code, doc = run_cli(["decide", run_id, "--repo", str(seeded), "--json", "--packet", "not-the-sha", "D1=approve"],
                        capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID and spawned == []


def test_decide_with_the_current_packet_records_the_answer_and_prints_the_shared_shape(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    sha = decisions.request(_run_dir(run_id), "propose", 1, kind="approval")
    code, doc = run_cli(["decide", run_id, "--stage", "propose", "--repo", str(seeded), "--json", "--packet", sha,
                         "D1=approve"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"]["status"] == "approved" and spawned == [run_id]


def test_check_reports_a_pending_decision_with_the_shared_shape(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    decisions.request(_run_dir(run_id), "propose", 1, kind="approval")
    code, doc = run_cli(["check", run_id, "--stage", "propose", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"]["status"] == "pending"


def test_check_of_a_run_with_no_open_stop_is_a_config_error(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    code, doc = run_cli(["check", run_id, "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID and doc["code"] == "decision.not_requested"


def test_reopen_leaves_a_pending_decision_alone_and_prints_the_shared_shape(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    decisions.request(_run_dir(run_id), "propose", 1, kind="approval")
    code, doc = run_cli(["reopen", run_id, "--stage", "propose", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK


def test_reopen_of_a_stage_with_no_decision_file_is_a_config_error(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    code, doc = run_cli(["reopen", run_id, "--stage", "propose", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID and doc["code"] == "decision.not_requested"


def test_open_opens_the_decision_page_in_the_browser_and_prints_the_shared_shape(seeded, capsys, spawned, monkeypatch):
    import webbrowser
    run_id = _add(seeded, capsys, spawned)
    decisions.request(_run_dir(run_id), "propose", 1, kind="approval")
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda uri: opened.append(uri) or True)
    code, doc = run_cli(["open", run_id, "--stage", "propose", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and opened and opened[0].startswith("file://") and opened[0].endswith("propose.1.html")


def test_open_of_a_stage_with_no_page_is_a_config_error(seeded, capsys, spawned, monkeypatch):
    import webbrowser
    run_id = _add(seeded, capsys, spawned)
    monkeypatch.setattr(webbrowser, "open", lambda uri: (_ for _ in ()).throw(AssertionError("no browser")))
    code, doc = run_cli(["open", run_id, "--stage", "propose", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID and doc["code"] == "decision.not_requested"


def _task(run_dir: Path, task_id: str, status: str = "running") -> None:
    """A task folder the engine would have written, so `note` has a task to queue on. Written under the run lock."""
    lock = acquire_lock(run_dir, "test")
    try:
        state.write_task(run_dir, TaskState(task_id=task_id, stage="implement", status=status, attempt=1, restarts=0,
                                            task_base=None, worktree=None, checkpoints=0), lock=lock)
    finally:
        release(lock)


def test_note_queues_a_note_for_a_running_task_and_prints_the_shared_shape(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    _task(_run_dir(run_id), "change")
    code, doc = run_cli(["note", run_id, "change", "use the new helper", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"]["task_id"] == "change" and doc["data"]["note_id"] == 1


def test_note_for_a_task_that_does_not_exist_is_a_config_error(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    code, doc = run_cli(["note", run_id, "no-such-task", "hello", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID and doc["code"] == "config.invalid"


def test_abort_ends_a_run_and_prints_the_shared_shape(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    code, doc = run_cli(["abort", run_id, "--reason", "test", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and state.read_run(_run_dir(run_id)).status == "aborted"


def test_abort_of_an_unknown_run_is_a_config_error(seeded, capsys, spawned):
    code, doc = run_cli(["abort", "no-such-run", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID


def test_resume_refuses_a_run_a_live_engine_holds_with_exit_5(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    holder = acquire_lock(_run_dir(run_id), "another-engine")
    try:
        code, doc = run_cli(["resume", run_id, "--repo", str(seeded), "--json"], capsys, **_factories())
    finally:
        release(holder)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_LOCKED and doc["code"] == "state.locked"


def test_recover_closes_open_attempts_and_prints_the_shared_shape(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    code, doc = run_cli(["recover", run_id, "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK


def test_recover_of_an_unknown_run_is_a_config_error(seeded, capsys, spawned):
    code, doc = run_cli(["recover", "no-such-run", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID


def test_status_lists_the_runs_and_prints_the_shared_shape(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    code, doc = run_cli(["status", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and [r["run_id"] for r in doc["data"]["runs"]] == [run_id]


def test_status_of_an_unknown_run_is_a_config_error(seeded, capsys, spawned):
    code, doc = run_cli(["status", "no-such-run", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID


def test_where_prints_the_run_paths_and_the_shared_shape(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    code, doc = run_cli(["where", run_id, "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"]["run_id"] == run_id


def test_events_prints_the_run_events_and_the_shared_shape(seeded, capsys, spawned):
    run_id = _add(seeded, capsys, spawned)
    code, doc = run_cli(["events", run_id, "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and isinstance(doc["data"]["events"], list)


def test_events_of_an_unknown_run_is_a_config_error(seeded, capsys, spawned):
    code, doc = run_cli(["events", "no-such-run", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID


def test_usage_prints_the_totals_and_the_shared_shape(seeded, capsys, spawned):
    code, doc = run_cli(["usage", "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and set(doc["data"]) >= {"by_model", "total"}


@pytest.mark.parametrize("since", ["notadate", "2026-13-01"])
def test_usage_with_a_bad_since_date_is_a_config_error_with_the_shared_shape(seeded, capsys, spawned, since):
    """A bad date must not leak a Python traceback (module 16: every command uses the shared shape and exit codes)."""
    code, doc = run_cli(["usage", "--since", since, "--repo", str(seeded), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID and doc["code"] == "config.invalid"


def test_gc_plan_prints_the_shared_shape(tmp_path, home, capsys):
    import subprocess as sp
    repo = tmp_path / "repo"
    repo.mkdir()
    sp.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    code, doc = run_cli(["gc", "--repo", str(repo), "--json"], capsys)
    _assert_shared_shape(doc, code, ok=True)
    assert code == EXIT_OK and doc["data"]["applied"] is False


def test_triage_outside_a_task_folder_is_a_config_error(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("FACTORY_TASK_DIR", raising=False)
    code, doc = run_cli(["triage", "--json"], capsys)
    _assert_shared_shape(doc, code, ok=False)
    assert code == EXIT_INVALID and doc["code"] == "config.invalid"
