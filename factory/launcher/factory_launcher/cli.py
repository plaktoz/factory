"""The `factory` command (module 16, ADR cli-parser-and-entry-points).

It runs the machine commands itself: tick, schedule, dashboard, inbox, doctor and config init. Every other command goes
to the engine of the repo the command is about, `python -m factory_engine <args>`, run with that repo's own kit, so
two repos on different kit versions each use their own engine.

The repo is found from --repo, else the git repo of the current folder, else the repo path recorded in the run's
run.json when the command names a run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from factory_engine import api, state
from factory_engine.errors import FactoryError
from factory_engine.loadcfg import load_config

from . import schedule as schedule_mod
from . import tick as tick_mod

MACHINE = {"tick", "watch", "schedule", "dashboard", "inbox", "doctor", "config", "triage"}
RUN_COMMANDS = {"resume", "recover", "status", "where", "events", "logs", "open", "decide", "check", "reopen",
                "note", "retry", "goto", "skip", "abort", "usage", "run", "add", "sync", "gc", "init", "upgrade",
                "intake", "sink", "plugins"}


def _emit(ok: bool, code: str, message: str, hint: str, data: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"ok": ok, "code": code, "message": message, "hint": hint, "data": data}))
    elif ok:
        print(message)
    else:
        print(f"{code}: {message}\nhint: {hint}", file=sys.stderr)


def _git_top(folder: Path) -> Path | None:
    out = subprocess.run(["git", "-C", str(folder), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                         check=False)
    return Path(out.stdout.strip()) if out.returncode == 0 else None


def find_repo(repo_arg: str | None, run_id: str | None, home: Path) -> Path | None:
    """The repo a command is about, or None when none applies. --repo first, then the run, then the current folder."""
    if repo_arg:
        return Path(repo_arg).resolve()
    if run_id:
        ref = state.find_run(home, run_id)
        if ref is None:
            raise FactoryError("config.invalid", f"no run named {run_id!r}", hint="factory status lists the runs in this repo")
        return ref.repo
    return _git_top(Path.cwd())


def _engine_argv(argv: list[str], repo: Path) -> list[str]:
    """`python -m factory_engine <argv> --repo <repo>` with the repo's kit: the engine reads that repo's own factory/."""
    return [sys.executable, "-m", "factory_engine", *argv, "--repo", str(repo)]


# Commands that set up or repair the kit itself. They run before a repo has an engine of its own, so they use the
# installed engine (otherwise `init` could never create one). Only `add` and `sync` create runs on the repo's engine.
KIT_COMMANDS = {"init", "upgrade", "doctor"}


def _dispatch(argv: list[str], repo: Path, home: Path, *, run_id: str | None = None, installed: bool = False) -> int:
    """Hand the command to an engine and pass its output and exit code straight through.

    A command about a run runs on that run's own kit snapshot (api.run_engine_env). A command that creates a run
    runs on the repo's own factory/engine. The kit commands and --installed-engine run on the installed engine."""
    env = {**os.environ, "FACTORY_HOME": str(home)}
    if not installed and argv and argv[0] not in KIT_COMMANDS:
        env = api.run_engine_env(run_id, home=home, env=env) if run_id else _repo_engine_env(repo, env)
    proc = subprocess.run(_engine_argv(argv, repo), cwd=str(repo), env=env, check=False)
    return proc.returncode


def _repo_engine_env(repo: Path, env: dict[str, str]) -> dict[str, str]:
    """PYTHONPATH for a command that creates a run: the repo's own factory/engine, which must exist."""
    engine = repo / "factory" / "engine"
    if not engine.is_dir():
        raise FactoryError("kit.no_engine", f"the repo's kit at {engine} has no engine folder",
                           hint="run factory init or factory upgrade, or add --installed-engine")
    return {**env, "PYTHONPATH": os.pathsep.join(p for p in (str(engine), env.get("PYTHONPATH", "")) if p)}


def _tick_repos(args, home: Path) -> list[Path]:
    repos = [Path(r).resolve() for r in (args.repo or [])]
    if args.all_repos:
        repos = sorted({ref.repo for ref in state.list_runs(home)}, key=str)
    return repos


def _tick_data(report: tick_mod.TickReport) -> dict:
    return {"skipped_tick": report.skipped_tick, "started": report.started, "resumed": report.resumed,
            "skipped": report.skipped, "repo_missing": report.repo_missing, "synced": report.synced,
            "errors": report.errors}


def _tick_message(report: tick_mod.TickReport) -> str:
    return ("tick skipped: another tick holds the lock" if report.skipped_tick
            else f"started {len(report.started)}, resumed {len(report.resumed)}")


def _tick(args, home: Path) -> int:
    cfg = load_config(None, env={"FACTORY_HOME": str(home)})
    report = tick_mod.tick(cfg, repos=_tick_repos(args, home), home=home)
    _emit(True, "ok" if not report.skipped_tick else "tick_skipped", _tick_message(report), "", _tick_data(report),
          args.json)
    return 0


def _watch(args, home: Path, *, sleep=time.sleep, rounds: int | None = None) -> int:
    """Run tick every --every until interrupted. Each tick prints as `tick` does, so --json gives one line per tick."""
    seconds = schedule_mod.interval_seconds(args.every)
    cfg = load_config(None, env={"FACTORY_HOME": str(home)})

    def show(report: tick_mod.TickReport) -> None:
        _emit(True, "ok" if not report.skipped_tick else "tick_skipped", _tick_message(report), "",
              _tick_data(report), args.json)

    done = 0
    try:
        while rounds is None or done < rounds:
            show(tick_mod.tick(cfg, repos=_tick_repos(args, home), home=home))
            done += 1
            if rounds is not None and done >= rounds:
                break
            sleep(seconds)
    except KeyboardInterrupt:
        pass
    return 0


def _schedule(args, home: Path) -> int:
    if args.action == "install":
        path = schedule_mod.install(args.every, home=home)
        _emit(True, "ok", f"installed {path}", "", {"path": str(path)}, args.json)
    else:
        removed = schedule_mod.remove(home=home)
        _emit(True, "ok", "removed" if removed else "nothing to remove", "", {"removed": removed}, args.json)
    return 0


def _dashboard(args, home: Path) -> int:
    if args.detach:
        return _dashboard_detached(args, home)
    from factory_launcher.server.serve import start
    from factory_launcher.server.settings import settings_from_home
    running = start(settings_from_home(home, port=args.port))
    _emit(True, "ok", running.url, "", {"url": running.url, "port": args.port}, args.json)
    try:
        running.server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def _spawn_dashboard_child(argv: list[str], home: Path) -> subprocess.Popen:
    """Start `factory_launcher.server` in its own session, its output going to dashboard-start.log."""
    with (home / "dashboard-start.log").open("w") as out:
        return subprocess.Popen([sys.executable, "-m", "factory_launcher.server", *argv],
                                env=dict(os.environ, FACTORY_HOME=str(home)), stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT, start_new_session=True)


def _dashboard_detached(args, home: Path) -> int:
    """Start the server as its own process, so it outlives this command (item 30). The child writes dashboard.json
    with its own pid and token; this command waits for that file, then prints the address the child is serving."""
    log = home / "dashboard-start.log"
    child = _spawn_dashboard_child(["--port", str(args.port)], home)
    info_path = home / "dashboard.json"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if child.poll() is not None:
            lines = [ln for ln in log.read_text().splitlines() if ln.strip() and not ln.startswith("hint:")]
            message = lines[-1].split(": ", 1)[1] if lines and lines[-1].startswith("dashboard.") else (
                lines[-1] if lines else f"the dashboard exited at start (code {child.returncode})")
            raise FactoryError("dashboard.port_in_use", message,
                               hint=f"run `factory dashboard --port {args.port}` in the foreground to see why")
        try:
            info = json.loads(info_path.read_text())
        except (OSError, ValueError):
            info = None
        if info and info.get("pid") == child.pid:
            log.unlink(missing_ok=True)
            url = f"http://127.0.0.1:{info['port']}/?token={info['token']}"
            _emit(True, "ok", url, "", {"url": url, "port": info["port"], "pid": child.pid}, args.json)
            return 0
        time.sleep(0.05)
    child.kill()
    raise FactoryError("dashboard.port_in_use", "the detached dashboard did not start within 10 seconds",
                       hint=f"run `factory dashboard --port {args.port}` in the foreground to see why")


def _inbox(args, home: Path) -> int:
    rows = []
    for ref in state.list_runs(home):
        run = state.read_run(ref.run_dir)
        if run.attention is None:
            continue
        rows.append({"run_id": run.run_id, "repo": str(ref.repo), "kind": run.attention.kind,
                     "summary": run.attention.summary, "page": str(run.attention.page) if run.attention.page else None,
                     "command": run.attention.command})
    if args.json:
        _emit(True, "ok", f"{len(rows)} item(s)", "", {"items": rows}, True)
    else:
        for r in rows:
            print(f"{r['run_id']} [{r['kind']}] {r['summary']}" + (f"\n  open: {r['page']}" if r["page"] else ""))
        if not rows:
            print("nothing needs you")
    return 0


def _triage(args, home: Path) -> int:
    """`factory triage`: the `rules` task of the triage stage. It runs in the task folder, which is not a repo, so it
    takes no repo and goes to the engine's triage code directly (module 4; the engine copies the request in)."""
    from factory_engine.triage_cli import run_triage
    try:
        run_triage()
    except FactoryError as e:
        _emit(False, e.code, e.message, e.hint, {}, getattr(args, "json", False))
        return e.exit_code
    _emit(True, "ok", "triage.json written", "", {"triage": "written"}, getattr(args, "json", False))
    return 0


def _config_init(args, home: Path) -> int:
    from factory_engine.loadcfg import factory_home
    target = home / "config.yaml"
    if target.exists():
        _emit(True, "ok", f"{target} already exists", "", {"path": str(target), "created": False}, args.json)
        return 0
    home.mkdir(parents=True, exist_ok=True)
    target.write_text("# Machine settings. Repo settings live in .factory/config/factory.yaml.\n"
                      "repos: []\n"
                      "tick: {every_minutes: 10, stale_after_ticks: 3}\n")
    _emit(True, "ok", f"wrote {target}", "", {"path": str(target), "created": True}, args.json)
    return 0


def _doctor(args, home: Path) -> int:
    from factory_engine import kit
    repo = None if args.no_repo else find_repo(args.repo, None, home)
    checks = kit.doctor(repo, as_scheduler=args.as_scheduler)
    failed = [c for c in checks if not c.ok]
    data = {"checks": [{"name": c.name, "ok": c.ok, "detail": c.detail, "hint": c.hint} for c in checks]}
    _emit(not failed, "ok" if not failed else "failed", f"{len(checks) - len(failed)} of {len(checks)} checks passed",
          "; ".join(f"{c.name}: {c.hint}" for c in failed if c.hint), data, args.json)
    return 0 if not failed else 1


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="factory", description="The factory on this machine. Other commands go to the repo's engine.")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    t = sub.add_parser("tick", help="one scheduled pass")
    t.add_argument("--all-repos", action="store_true", help="sync every repo that has a run")
    t.add_argument("--repo", action="append", dest="repo", help="a repo to sync (repeatable)")
    t.add_argument("--env-file", help="variables for the scheduler's environment (read by the harness, not here)")
    t.add_argument("--json", action="store_true")

    w = sub.add_parser("watch", help="run tick in a foreground loop")
    w.add_argument("--every", default="10m", help="interval between ticks, such as 10m")
    w.add_argument("--all-repos", action="store_true", help="sync every repo that has a run")
    w.add_argument("--repo", action="append", dest="repo", help="a repo to sync (repeatable)")
    w.add_argument("--json", action="store_true")

    s = sub.add_parser("schedule", help="install or remove the OS scheduler entry for tick")
    s.add_argument("action", choices=["install", "remove"])
    s.add_argument("--every", default="10m", help="interval, such as 10m")
    s.add_argument("--json", action="store_true")

    d = sub.add_parser("dashboard", help="start the dashboard server")
    d.add_argument("--port", type=int, default=8765)
    d.add_argument("--detach", action="store_true")
    d.add_argument("--json", action="store_true")

    i = sub.add_parser("inbox", help="attention items across all repos")
    i.add_argument("--json", action="store_true")

    dr = sub.add_parser("doctor", help="check the machine and the repo")
    dr.add_argument("--repo", help="the repo to check (default: the current git repo)")
    dr.add_argument("--as-scheduler", action="store_true")
    dr.add_argument("--no-repo", action="store_true")
    dr.add_argument("--json", action="store_true")

    tr = sub.add_parser("triage", help="the rules task of the triage stage: write triage.json from the task's request")
    tr.add_argument("--json", action="store_true")
    c = sub.add_parser("config", help="machine config")
    c.add_argument("action", choices=["init"])
    c.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = _parser()
    if argv and argv[0] not in MACHINE and argv[0] not in ("-h", "--help"):
        return _engine_passthrough(argv)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    home = state.factory_home()
    try:
        if args.command == "tick":
            return _tick(args, home)
        if args.command == "watch":
            return _watch(args, home)
        if args.command == "schedule":
            return _schedule(args, home)
        if args.command == "dashboard":
            return _dashboard(args, home)
        if args.command == "inbox":
            return _inbox(args, home)
        if args.command == "doctor":
            return _doctor(args, home)
        if args.command == "config":
            return _config_init(args, home)
        if args.command == "triage":
            return _triage(args, home)
    except FactoryError as e:
        _emit(False, e.code, e.message, e.hint, {}, getattr(args, "json", False))
        return e.exit_code
    return 2


def _engine_passthrough(argv: list[str]) -> int:
    """Send a run command to its engine. The repo comes from --repo, the run's run.json, or the current folder.

    --installed-engine is taken out here, so the engine never sees it, and the command runs on the installed engine."""
    home = state.factory_home()
    args_list = list(argv)
    installed = "--installed-engine" in args_list
    args_list = [a for a in args_list if a != "--installed-engine"]
    repo_arg = None
    if "--repo" in args_list:
        i = args_list.index("--repo")
        repo_arg = args_list[i + 1]
        del args_list[i:i + 2]
    run_id = next((a for a in args_list if not a.startswith("-") and _is_run(a, home)), None)
    try:
        repo = find_repo(repo_arg, run_id, home)
    except FactoryError as e:
        _emit(False, e.code, e.message, e.hint, {}, "--json" in argv)
        return e.exit_code
    if repo is None:
        _emit(False, "config.invalid", "the current folder is not in a git repo", "pass --repo <path>", {}, "--json" in argv)
        return 2
    try:
        return _dispatch(args_list, repo, home, run_id=run_id, installed=installed)
    except FactoryError as e:
        _emit(False, e.code, e.message, e.hint, {}, "--json" in argv)
        return e.exit_code


def _is_run(value: str, home: Path) -> bool:
    return state.find_run(home, value) is not None
