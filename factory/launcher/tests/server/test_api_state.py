"""Module 15: the overview, the run detail, Needs you, scheduler health and the 500-run refresh rule."""

import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from factory_engine import state
from factory_engine.lock import acquire_lock, release
from factory_engine.types import StageState, TaskState
from factory_launcher.server import runs as runs_module
from factory_launcher.server.app import App
from factory_launcher.server.settings import Settings

from factory_launcher.server.settings import settings_from_home
from helpers import (PORT, TOKEN, approval_page, attention_for, call, get_json, make_repo, make_run, set_run,
                       state_doc, write_tick)


def _task(run_dir: Path, task_id: str, *, worktree: Path | None, status: str = "running") -> None:
    """A task.json and its folder, written the way the lock holder writes it."""
    lock = acquire_lock(run_dir, "engine")
    try:
        state.write_task(run_dir, TaskState(task_id=task_id, stage="fix", status=status, attempt=1, restarts=0,
                                            task_base=None, worktree=worktree, checkpoints=0), lock=lock)
    finally:
        release(lock)


# --- criterion: runs from two repos with different kit versions show on one page ---

def test_runs_from_two_repos_on_different_kits_show_on_one_page(home, app, tmp_path):
    make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa", kit_hash="kit-v1")
    make_run(home, make_repo(tmp_path, "portal"), key="github.com/acme/portal", run_id="gather-b-bbbbb", kit_hash="kit-v9")
    doc = state_doc(app)
    rows = {r["run_id"]: r for r in doc["runs"]}
    assert set(rows) == {"fix-a-aaaaa", "gather-b-bbbbb"}
    assert {rows[k]["repo_key"] for k in rows} == {"github.com/acme/payments", "github.com/acme/portal"}
    assert {rows[k]["kit_hash"] for k in rows} == {"kit-v1", "kit-v9"}


# --- criterion: a new run appears on the next refresh; an archived run disappears ---

def test_a_new_run_and_an_archived_run_show_on_the_next_refresh(home, app, tmp_path):
    """The server half of the criterion: each refresh rescans the factory home. The page's own 5 s poll is not
    tested here (Playwright is out of scope for this change)."""
    assert state_doc(app)["runs"] == []
    ref = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    assert [r["run_id"] for r in state_doc(app)["runs"]] == ["fix-a-aaaaa"]
    shutil.rmtree(ref.run_dir)  # what housekeeping does when it archives a run
    assert state_doc(app)["runs"] == []


# --- criterion: with 500 runs, a refresh re-reads only the run files that changed ---

def test_with_500_runs_a_refresh_rereads_only_changed_files(home, app, tmp_path, monkeypatch):
    repo = make_repo(tmp_path, "payments")
    refs = [make_run(home, repo, key="github.com/acme/payments", run_id=f"fix-{i:03d}-aaaaa") for i in range(500)]
    reads = []
    real_read_run = runs_module.read_run

    def counting(run_dir):
        reads.append(run_dir.name)
        return real_read_run(run_dir)
    monkeypatch.setattr(runs_module, "read_run", counting)

    assert len(state_doc(app)["runs"]) == 500
    assert len(reads) == 500  # the first refresh reads every run once
    reads.clear()

    state_doc(app)
    assert reads == []  # nothing changed: no run file is read

    set_run(refs[7], [], status="running", stage="build")  # one run.json changes
    doc = state_doc(app)
    assert reads == [refs[7].run_id]
    assert {r["run_id"]: r["status"] for r in doc["runs"]}[refs[7].run_id] == "running"


# --- criterion: a run whose repo was deleted shows as repo missing and can still be opened ---

def test_a_run_whose_repo_was_deleted_shows_as_repo_missing_and_opens(home, app, tmp_path):
    repo = make_repo(tmp_path, "payments")
    make_run(home, repo, key="github.com/acme/payments", run_id="fix-a-aaaaa")
    shutil.rmtree(repo)
    row = {r["run_id"]: r for r in state_doc(app)["runs"]}["fix-a-aaaaa"]
    assert row["repo_missing"] is True
    status, detail = get_json(app, "/api/runs/fix-a-aaaaa")
    assert status == 200
    assert detail["repo_missing"] is True and detail["run"]["run_id"] == "fix-a-aaaaa"


# --- criterion: Needs you lists every attention item across repos, oldest first ---

def test_needs_you_lists_every_attention_item_across_repos_oldest_first(home, app, tmp_path, now, held):
    a = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    b = make_run(home, make_repo(tmp_path, "portal"), key="github.com/acme/portal", run_id="gather-b-bbbbb")
    page_a = approval_page(a)
    page_b = approval_page(b)
    set_run(a, held, status="awaiting_approval", stage="propose",
            attention=attention_for(a, page=page_a, since="2026-11-15T10:00:00+00:00"))
    set_run(b, held, status="awaiting_approval", stage="propose",
            attention=attention_for(b, page=page_b, since="2026-11-15T09:00:00+00:00"))
    doc = state_doc(app)
    assert [item["run_id"] for item in doc["attention"]] == ["gather-b-bbbbb", "fix-a-aaaaa"]
    assert doc["counters"]["needs_you"] == 2
    first = doc["attention"][0]
    assert first["page_path"] == str(page_b)
    assert first["page_url"] == f"/runs/gather-b-bbbbb/decisions/propose.1.html"


def test_an_attention_item_without_a_page_gives_a_command(home, app, tmp_path, held):
    ref = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    set_run(ref, held, status="blocked", stage="verify",
            attention=attention_for(ref, kind="blocked", stage="verify", summary="Gate failed"))
    item = state_doc(app)["attention"][0]
    assert item["page_url"] is None and item["command"].startswith("factory decide fix-a-aaaaa")


# --- criterion: run detail shows repo, worktree, task worktrees, branch and source paths ---

def test_run_detail_lists_repo_worktree_task_worktrees_branch_and_source(home, app, tmp_path):
    repo = make_repo(tmp_path, "payments")
    ref = make_run(home, repo, key="github.com/acme/payments", run_id="fix-a-aaaaa")
    _task(ref.run_dir, "backend", worktree=tmp_path / "wt-backend")
    _task(ref.run_dir, "tests", worktree=tmp_path / "wt-tests")
    status, detail = get_json(app, "/api/runs/fix-a-aaaaa")
    assert status == 200
    labels = {p["label"]: p["value"] for p in detail["paths"]}
    assert labels["Repo"] == str(repo)
    assert labels["Worktree"] == str(repo.parent / "fix-a-aaaaa-wt")
    assert labels["Task backend worktree"] == str(tmp_path / "wt-backend")
    assert labels["Task tests worktree"] == str(tmp_path / "wt-tests")
    assert labels["Branch"] == "fix-a-aaaaa"
    assert labels["Source"] == "acme/report#42"


# --- criterion: scheduler health shows the last tick from tick.json, and warns after stale_after_ticks ---

def test_scheduler_health_shows_the_last_tick_and_warns_when_it_is_stale(home, settings, app, now):
    write_tick(home, now - timedelta(minutes=5), "2 runs started")
    tick = state_doc(app)["tick"]
    assert tick["last_tick"] == (now - timedelta(minutes=5)).isoformat(timespec="seconds")
    assert tick["warning"] is False and "last tick 5 min ago" in tick["message"]

    write_tick(home, now - timedelta(minutes=31))  # stale_after_ticks 3 x every 10 min = 30 min
    tick = state_doc(app)["tick"]
    assert tick["warning"] is True and "no tick for more than 3 intervals" in tick["message"]


def test_scheduler_health_warns_when_tick_json_is_missing(app):
    tick = state_doc(app)["tick"]
    assert tick["last_tick"] is None and tick["warning"] is True


# --- counters, grouping and the finished-run window ---

def test_counters_count_running_blocked_warnings_and_done_today(home, app, tmp_path, held, now):
    repo = make_repo(tmp_path, "payments")
    running = make_run(home, repo, key="github.com/acme/payments", run_id="fix-a-aaaaa")
    blocked = make_run(home, repo, key="github.com/acme/payments", run_id="fix-b-bbbbb")
    done = make_run(home, repo, key="github.com/acme/payments", run_id="fix-c-ccccc")
    set_run(running, held, status="running", stage="build", hold=True)
    set_run(blocked, [], status="blocked", stage="verify")
    set_run(done, [], status="done", stage="deliver")
    counters = state_doc(app)["counters"]
    assert counters["running"] == 1 and counters["blocked"] == 1
    assert counters["done_today"] == 1 and counters["conflict_warnings"] == 0


def test_finished_runs_older_than_show_finished_days_are_hidden(home, app, tmp_path, now):
    repo = make_repo(tmp_path, "payments")
    old = make_run(home, repo, key="github.com/acme/payments", run_id="fix-old-aaaaa")
    recent = make_run(home, repo, key="github.com/acme/payments", run_id="fix-new-bbbbb")
    set_run(old, [], status="done", stage="deliver", now=now, age=timedelta(days=8))
    set_run(recent, [], status="done", stage="deliver", now=now, age=timedelta(days=1))
    rows = {r["run_id"]: r for r in state_doc(app)["runs"]}
    assert rows["fix-old-aaaaa"]["hidden"] is True
    assert rows["fix-new-bbbbb"]["hidden"] is False


def test_a_stale_run_shows_as_stale_for_display(home, app, tmp_path, held):
    ref = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    set_run(ref, [], status="running", stage="build")  # running in run.json, no process holds the lock
    row = state_doc(app)["runs"][0]
    assert row["status"] == "running" and row["display_status"] == "stale"


# --- a bad file is a row, not a failed page ---

def test_a_corrupt_run_json_shows_as_an_unreadable_row(home, app, tmp_path):
    ref = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    (ref.run_dir / "run.json").write_text("{not json")
    (ref.run_dir / "events.jsonl").unlink(missing_ok=True)
    status, doc = get_json(app, "/api/state.json")
    assert status == 200
    row = doc["runs"][0]
    assert row["display_status"] == "unreadable" and row["unreadable"]


def test_a_task_log_is_the_last_200_lines_of_worker_log(home, app, tmp_path):
    ref = make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    _task(ref.run_dir, "backend", worktree=None)
    lines = [f"line {i}" for i in range(1, 301)]
    (ref.run_dir / "tasks" / "backend" / "worker.log").write_text("\n".join(lines) + "\n")
    resp = call(app, "GET", "/api/runs/fix-a-aaaaa/tasks/backend/log")
    assert resp.status == 200 and resp.content_type.startswith("text/plain")
    body = resp.body.decode().splitlines()
    assert len(body) == 200 and body[0] == "line 101" and body[-1] == "line 300"


def test_an_unknown_run_or_task_log_is_404(home, app, tmp_path):
    make_run(home, make_repo(tmp_path, "payments"), key="github.com/acme/payments", run_id="fix-a-aaaaa")
    assert call(app, "GET", "/api/runs/nope-zzzzz").status == 404
    assert call(app, "GET", "/api/runs/fix-a-aaaaa/tasks/backend/log").status == 404


# --- the machine config sets how long finished runs show and the scheduler's interval (modules 6 and 15) ---

def test_show_finished_days_and_the_tick_interval_come_from_the_machine_config(home):
    (home / "config.yaml").write_text("show_finished_days: 2\ntick: {every_minutes: 5, stale_after_ticks: 4}\n")
    s = settings_from_home(home)
    assert (s.show_finished_days, s.tick_every_minutes, s.stale_after_ticks) == (2, 5, 4)


def test_without_a_machine_config_the_spec_defaults_apply(home):
    s = settings_from_home(home)
    assert (s.show_finished_days, s.tick_every_minutes, s.stale_after_ticks) == (7, 10, 3)
