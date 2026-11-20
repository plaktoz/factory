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
import subprocess
import sys
from pathlib import Path

from factory_engine import state
from factory_engine.errors import FactoryError
from factory_engine.loadcfg import load_config

from . import schedule as schedule_mod
from . import tick as tick_mod

MACHINE = {"tick", "schedule", "dashboard", "inbox", "doctor", "config"}
RUN_COMMANDS = {"resume", "recover", "status", "where", "events", "logs", "open", "decide", "check", "reopen",
                "note", "retry", "goto", "skip", "abort", "usage", "run", "add", "sync", "gc", "init", "upgrade",
                "intake", "triage", "sink", "plugins"}


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


def _dispatch(argv: list[str], repo: Path, home: Path) -> int:
    """Hand the command to the repo's engine and pass its output and exit code straight through."""
    env = {**__import__("os").environ, "FACTORY_HOME": str(home)}
    proc = subprocess.run(_engine_argv(argv, repo), cwd=str(repo), env=env, check=False)
    return proc.returncode


def _tick(args, home: Path) -> int:
    repos = [Path(r).resolve() for r in (args.repo or [])]
    if args.all_repos:
        repos = sorted({ref.repo for ref in state.list_runs(home)}, key=str)
    cfg = load_config(None, env={"FACTORY_HOME": str(home)})
    report = tick_mod.tick(cfg, repos=repos, home=home)
    data = {"skipped_tick": report.skipped_tick, "started": report.started, "resumed": report.resumed,
            "skipped": report.skipped, "repo_missing": report.repo_missing, "synced": report.synced,
            "errors": report.errors}
    _emit(True, "ok" if not report.skipped_tick else "tick_skipped",
          "tick skipped: another tick holds the lock" if report.skipped_tick
          else f"started {len(report.started)}, resumed {len(report.resumed)}", "", data, args.json)
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
    from factory_launcher.server.serve import start
    from factory_launcher.server.settings import settings_from_home
    running = start(settings_from_home(home, port=args.port))
    _emit(True, "ok", running.url, "", {"url": running.url, "port": args.port}, args.json)
    if args.detach:
        return 0
    try:
        running.server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


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
    except FactoryError as e:
        _emit(False, e.code, e.message, e.hint, {}, getattr(args, "json", False))
        return e.exit_code
    return 2


def _engine_passthrough(argv: list[str]) -> int:
    """Send a run command to its engine. The repo comes from --repo, the run's run.json, or the current folder."""
    home = state.factory_home()
    args_list = list(argv)
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
    return _dispatch(args_list, repo, home)


def _is_run(value: str, home: Path) -> bool:
    return state.find_run(home, value) is not None
