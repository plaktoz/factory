"""The repo engine's command line (module 16): `python -m factory_engine <command>`.

argparse parses the commands (ADR cli-parser-and-entry-points). Every command prints one JSON object with --json and
exits with the shared codes (section 18). A FactoryError maps by its kind. CLI misuse exits 2 from argparse, and with
--json the misuse still prints the shared shape.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import api, decisions, kit, state, usage as usage_mod
from .errors import EXIT_BLOCKED, EXIT_FAILED, EXIT_INVALID, EXIT_OK, EXIT_WAITING_HUMAN, FactoryError
from .gh import ALL_LABELS
from .loadcfg import load_config
from .types import RunRef

_WANTS_JSON = {"on": False}  # set by main() before parsing, so a usage error can still print the shared shape


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        if _WANTS_JSON["on"]:
            _emit_json(False, "cli.usage", message, self.format_usage().strip(), {})
            raise SystemExit(EXIT_INVALID)
        self.print_usage(sys.stderr)
        self.exit(EXIT_INVALID, f"{self.prog}: error: {message}\n")


def _jsonable(value: Any):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _emit_json(ok: bool, code: str, message: str, hint: str, data: dict) -> None:
    print(json.dumps({"ok": ok, "code": code, "message": message, "hint": hint, "data": data}, default=_jsonable))


class _Result:
    """What a handler returns: the JSON data, the exit code, and the one-line message."""

    def __init__(self, data: dict, code: int = EXIT_OK, message: str = "ok", hint: str = ""):
        self.data, self.code, self.message, self.hint = data, code, message, hint


# ---- finding the repo -----------------------------------------------------------------------------------------

def _repo_here(args) -> Path:
    """--repo, else the git top level of the current folder."""
    if getattr(args, "repo", None):
        return Path(args.repo).resolve()
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise FactoryError("config.invalid", "the current folder is not inside a git repo", hint="pass --repo <path>")
    return Path(out.stdout.strip())


def _repo_of_run(args, run_id: str) -> Path:
    """--repo, else the repo path recorded in the run's run.json, so a run id works from any folder."""
    if getattr(args, "repo", None):
        return Path(args.repo).resolve()
    ref = state.find_run(state.factory_home(), run_id)
    if ref is None:
        raise FactoryError("config.invalid", f"no run named {run_id!r}", hint="factory status lists the runs in this repo")
    return ref.repo


def _ref(run_id: str) -> RunRef:
    ref = state.find_run(state.factory_home(), run_id)
    if ref is None:
        raise FactoryError("config.invalid", f"no run named {run_id!r}", hint="factory status lists the runs in this repo")
    return ref


def _latest_stop_stage(run_dir: Path) -> str:
    run = state.read_run(run_dir)
    waiting = [s.id for s in run.stages if s.status == "awaiting_approval"]
    if waiting:
        return waiting[-1]
    if run.stage is None:
        raise FactoryError("decision.not_requested", f"run {run.run_id} has no open stop",
                           hint="factory status shows the runs and their stages")
    return run.stage


def _pairs(items: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key or not value:
            raise FactoryError("decision.bad_choice", f"{item!r} is not ID=option", hint="write D1=opt-a, one per decision")
        out[key] = value
    return out


# ---- handlers --------------------------------------------------------------------------------------------------
# Each handler takes (args, factories) and returns a _Result. Anything that starts an engine calls factories.spawn.

def _triage(args, f) -> _Result:
    """Internal (module 16): the `rules` task's command. It reads the request the engine copied into its task folder."""
    from .triage_cli import run_triage
    run_triage()
    return _Result({"triage": "written"}, message="triage.json written")


def _init(args, f) -> _Result:
    repo = _repo_here(args)
    report = kit.init_repo(repo)
    data: dict = {"created": [str(p) for p in report.created], "unchanged": [str(p) for p in report.unchanged]}
    if args.github:
        f.tracker(repo).ensure_labels(list(ALL_LABELS))
        data["labels"] = list(ALL_LABELS)
    return _Result(data, message=f"{len(report.created)} created, {len(report.unchanged)} unchanged")


def _upgrade(args, f) -> _Result:
    report = kit.upgrade(_repo_here(args), args.version)
    if report.problems:
        raise FactoryError("config.invalid", "; ".join(report.problems),
                           hint="fix the config named above, then upgrade again")
    return _Result({"replaced": str(report.replaced), "config_untouched": report.config_untouched},
                   message="factory/ replaced")


def _doctor(args, f) -> _Result:
    repo = None if args.no_repo else _repo_here(args)
    checks = kit.doctor(repo, as_scheduler=args.as_scheduler)
    failed = [c for c in checks if not c.ok]
    return _Result({"checks": [asdict(c) for c in checks]}, code=EXIT_FAILED if failed else EXIT_OK,
                   message=f"{len(checks) - len(failed)} of {len(checks)} checks passed",
                   hint="; ".join(f"{c.name}: {c.hint}" for c in failed if c.hint))


def _add(args, f) -> _Result:
    repo = _repo_here(args)
    body = None
    if args.body is not None:
        path = Path(args.body)
        if not path.is_file():
            raise FactoryError("config.invalid", f"body file {args.body} does not exist", hint="pass a readable file")
        body = path.read_text()
    ref = api.add(repo, args.title, type=args.type, body=body, files=[Path(p) for p in args.files or []])
    pid = None if args.no_run else f.spawn(repo, ref.run_id)
    return _Result({"run_id": ref.run_id, "repo": str(repo), "started_pid": pid}, message=f"created run {ref.run_id}")


def _sync(args, f) -> _Result:
    report = api.sync(_repo_here(args))
    return _Result({"created": [r.run_id for r in report.created], "invalid": report.invalid,
                    "duplicates": report.duplicates, "changed": report.changed},
                   message=f"{len(report.created)} new run(s)")


def _run(args, f) -> _Result:
    if not args.runs and not args.all:
        raise FactoryError("config.invalid", "factory run needs a run id or --all", hint="name a run, or pass --all")
    if args.runs:
        repo = _repo_of_run(args, args.runs[0])
        run_ids = list(args.runs)
    else:
        repo = _repo_here(args)
        run_ids = [r.run_id for r in state.list_runs(state.factory_home(), key=_repo_key(repo))]
    if args.detach:
        pids = {rid: f.spawn(repo, rid) for rid in run_ids}
        return _Result({"started": pids}, message=f"started {sum(1 for v in pids.values() if v)} engine(s)")
    result = f.engine(repo).run(run_ids or None, poll_seconds=args.poll)
    return _Result({"runs": result.runs}, code=result.exit_code,
                   message=", ".join(f"{rid} {status}" for rid, status in result.runs.items()) or "no runs to drive",
                   hint=_run_hint(result.runs))


def _run_hint(runs: dict) -> str:
    if "blocked" in runs.values():
        return "factory status shows what blocked it; then retry, goto or skip it"
    if "awaiting_approval" in runs.values():
        return "factory inbox lists the decisions to answer"
    return ""


def _repo_key(repo: Path) -> str:
    return state.repo_key(repo, load_config(repo))


def _decide(args, f) -> _Result:
    ref = _ref(args.run)
    repo = _repo_of_run(args, args.run)
    stage = args.stage or _latest_stop_stage(ref.run_dir)
    outcome = api.decide(repo, args.run, stage, packet_sha=args.packet, choices=_pairs(args.answers) or None,
                         questions=_pairs(args.question) or None, notes=args.notes, by=args.by or "cli",
                         channel="cli")
    # An engine must see every answer that moves or ends the run. A pending or rejected answer changes nothing.
    pid = f.spawn(repo, args.run) if outcome.status in ("approved", "rework", "reject", "question") else None
    return _Result({"status": outcome.status, "stage": stage, "started_pid": pid},
                   message=f"{args.run} {stage}: {outcome.status}")


def _check(args, f) -> _Result:
    ref = _ref(args.run)
    stage = args.stage or _latest_stop_stage(ref.run_dir)
    visit = decisions.latest_visit(state.read_run(ref.run_dir), stage)
    outcome = decisions.evaluate(ref.run_dir, stage, visit)
    return _Result({"status": outcome.status, "stage": stage, "code": outcome.code, "message": outcome.message},
                   message=f"{args.run} {stage}: {outcome.status}")


def _reopen(args, f) -> _Result:
    ref = _ref(args.run)
    stage = args.stage or _latest_stop_stage(ref.run_dir)
    decisions.reopen(ref.run_dir, stage, decisions.latest_visit(state.read_run(ref.run_dir), stage), by=args.by or "cli")
    return _Result({"stage": stage}, message=f"{args.run} {stage} reopened")


def _open(args, f) -> _Result:
    import webbrowser
    ref = _ref(args.run)
    stage = args.stage or _latest_stop_stage(ref.run_dir)
    page = decisions.page_path(ref.run_dir, stage, decisions.latest_visit(state.read_run(ref.run_dir), stage))
    if not page.is_file():
        raise FactoryError("decision.not_requested", f"no decision page for {stage}",
                           hint="the page is written when the stop begins")
    webbrowser.open(page.as_uri())
    return _Result({"page": str(page)}, message=f"opened {page}")


def _note(args, f) -> _Result:
    ref = api.note(_repo_of_run(args, args.run), args.run, args.task, args.text, deny=args.deny)
    return _Result({"task_id": ref.task_id, "note_id": ref.note_id}, message=f"note {ref.note_id} queued")


def _retry(args, f) -> _Result:
    repo = _repo_of_run(args, args.run)
    api.retry(repo, args.run, stage=args.stage, note=args.note)
    return _Result({"started_pid": f.spawn(repo, args.run)}, message=f"{args.run} retried")


def _goto(args, f) -> _Result:
    repo = _repo_of_run(args, args.run)
    api.goto(repo, args.run, args.stage)
    return _Result({"started_pid": f.spawn(repo, args.run)}, message=f"{args.run} routed to {args.stage}")


def _skip(args, f) -> _Result:
    repo = _repo_of_run(args, args.run)
    api.skip(repo, args.run, args.gate, reason=args.reason)
    return _Result({"started_pid": f.spawn(repo, args.run)}, message=f"{args.run} skipped gate {args.gate}")


def _abort(args, f) -> _Result:
    api.abort(_repo_of_run(args, args.run), args.run, reason=args.reason or "aborted from the CLI")
    return _Result({}, message=f"{args.run} aborted")


def _resume(args, f) -> _Result:
    ref = _ref(args.run)
    f.engine(ref.repo).resume(args.run)
    status = state.read_run(ref.run_dir).status
    return _Result({"status": status}, code=_code_of_status(status), message=f"{args.run} is {status}")


def _recover(args, f) -> _Result:
    api.recover(_repo_of_run(args, args.run), args.run, rebuild=args.rebuild)
    return _Result({"rebuilt": args.rebuild}, message=f"{args.run} recovered")


def _status(args, f) -> _Result:
    repo = _repo_of_run(args, args.run) if args.run else _repo_here(args)
    refs = state.list_runs(state.factory_home(), key=_repo_key(repo))
    if args.run:
        refs = [r for r in refs if r.run_id == args.run]
        if not refs:
            raise FactoryError("config.invalid", f"no run named {args.run!r} in this repo",
                               hint="factory status lists the runs in this repo")
    rows = []
    for r in refs:
        run = state.read_run(r.run_dir)
        rows.append({"run_id": run.run_id, "status": run.status, "stage": run.stage, "workflow": run.workflow,
                     "title": run.request.title, "stages": [{"id": s.id, "status": s.status} for s in run.stages],
                     "pr": run.pr.url if run.pr else None,
                     "attention": None if run.attention is None else
                     {"kind": run.attention.kind, "stage": run.attention.stage, "summary": run.attention.summary,
                      "page": run.attention.page, "command": run.attention.command}})
    return _Result({"repo": str(repo), "runs": rows}, message=f"{len(rows)} run(s)")


def _where(args, f) -> _Result:
    ref = _ref(args.run)
    run = state.read_run(ref.run_dir)
    return _Result({"run_id": run.run_id, "repo": str(ref.repo), "run_dir": str(ref.run_dir),
                    "worktree": str(run.worktree), "branch": run.branch, "status": run.status},
                   message=f"run folder {ref.run_dir}")


def _events(args, f) -> _Result:
    events = state.read_events(_ref(args.run).run_dir)[-args.tail:]
    return _Result({"events": [{"seq": e.seq, "ts": e.ts, "type": e.type, "data": e.data} for e in events]},
                   message=f"{len(events)} event(s)")


def _usage(args, f) -> _Result:
    repo = _repo_of_run(args, args.run) if args.run else _repo_here(args)
    since = date.fromisoformat(args.since) if args.since else None
    report = api.usage(repo, args.run, since=since)
    return _Result({"by_model": report.by_model, "by_repo": report.by_repo, "by_day": report.by_day},
                   message="usage totals")


def _gc(args, f) -> _Result:
    plan = api.gc(_repo_here(args), apply=args.apply)
    return _Result({"applied": args.apply,
                    "items": [{"kind": i.kind, "path": i.path, "run_id": i.run_id} for i in plan.items],
                    "skipped": [{"path": s.path, "reason": s.reason} for s in plan.skipped]},
                   message=("applied" if args.apply else "plan only") + f": {len(plan.items)} item(s)")


def _code_of_status(status: str) -> int:
    return {"done": EXIT_OK, "awaiting_approval": EXIT_WAITING_HUMAN, "blocked": EXIT_BLOCKED,
            "failed": EXIT_FAILED, "aborted": EXIT_FAILED}.get(status, EXIT_OK)


# ---- the adapters a command uses; a test passes its own through main() ----------------------------------------

class Factories:
    """Builds the adapters. The factories passed to main() replace the real ones; the defaults are the real adapters."""

    def __init__(self, *, worker_factory=None, tracker_factory=None, prs_factory=None, command_factory=None):
        self._worker = worker_factory or api.default_workers
        self._command = command_factory
        self._tracker = tracker_factory or api.default_tracker
        self._prs = prs_factory or api.default_prs

    def spawn(self, repo: Path, run_id: str) -> int | None:
        # Looked up at call time, so a test can replace api.spawn_engine and no engine process starts.
        return api.spawn_engine(repo, run_id)

    def tracker(self, repo: Path):
        return self._tracker(repo, load_config(repo))

    def engine(self, repo: Path):
        cfg = load_config(repo)
        command = self._command(cfg) if self._command else None
        return api.engine_for(repo, cfg, workers=self._worker(cfg), tracker=self._tracker(repo, cfg),
                              prs=self._prs(repo, cfg), command=command)


# ---- the parser ------------------------------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python -m factory_engine", description="Drive the factory in one repo. Every command takes --json.")
    sub = p.add_subparsers(dest="command", metavar="<command>", parser_class=_Parser, required=True)

    def add(name: str, handler: Callable, *, help: str, repo: bool = True) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help, description=help)
        if repo:
            sp.add_argument("--repo", help="the repo folder (default: the git repo here, or the run's own repo)")
        sp.add_argument("--json", action="store_true", help="print one JSON object")
        sp.set_defaults(handler=handler)
        return sp

    sp = add("triage", _triage, help="the rules task of the triage stage: write triage.json from the task's request",
             repo=False)
    sp = add("init", _init, help="create .factory/ and the kit for this repo")
    sp.add_argument("--github", action="store_true", help="also create the factory labels on GitHub")

    sp = add("upgrade", _upgrade, help="replace factory/ with this version")
    sp.add_argument("version")

    sp = add("doctor", _doctor, help="check git, gh, credentials and the repo's settings")
    sp.add_argument("--as-scheduler", action="store_true", help="run the checks in a cron-like environment")
    sp.add_argument("--no-repo", action="store_true", help="check the machine only")

    sp = add("add", _add, help="create a run from text or files")
    sp.add_argument("title")
    sp.add_argument("--type", help="bug, chore, feature, new-app or research")
    sp.add_argument("--body", help="a file with the request body")
    sp.add_argument("--files", nargs="*", help="markdown files that make up the request")
    sp.add_argument("--no-run", action="store_true", help="create the run without starting an engine")

    add("sync", _sync, help="read sources once and create runs, starting no engines")

    sp = add("run", _run, help="drive runs until each is done, blocked, failed or waiting")
    sp.add_argument("runs", nargs="*", metavar="run")
    sp.add_argument("--all", action="store_true", help="every run in this repo")
    sp.add_argument("--detach", action="store_true", help="start the engine in the background and print its pid")
    sp.add_argument("--poll", type=int, default=5, help="seconds between passes")

    sp = add("decide", _decide, help="answer a human stop")
    sp.add_argument("run")
    sp.add_argument("--stage", help="the stop's stage (default: the open one)")
    sp.add_argument("--packet", required=True, help="the packet sha the page shows")
    sp.add_argument("answers", nargs="*", metavar="D1=opt-a", help="one option per decision, in any position")
    sp.add_argument("--notes", default="")
    sp.add_argument("--question", action="append", metavar="D1=text", help="ask about a decision instead of answering")
    sp.add_argument("--by", help="who answers")

    sp = add("check", _check, help="re-evaluate a decision file")
    sp.add_argument("run")
    sp.add_argument("--stage")

    sp = add("reopen", _reopen, help="unlock an approved decision")
    sp.add_argument("run")
    sp.add_argument("--stage")
    sp.add_argument("--by")

    sp = add("open", _open, help="open the decision page in the browser")
    sp.add_argument("run")
    sp.add_argument("--stage")

    sp = add("note", _note, help="queue a note for a task")
    sp.add_argument("run")
    sp.add_argument("task")
    sp.add_argument("text")
    sp.add_argument("--deny", action="append", help="a path glob the note may not touch")

    sp = add("retry", _retry, help="run a blocked stage once more")
    sp.add_argument("run")
    sp.add_argument("--stage")
    sp.add_argument("--note")

    sp = add("goto", _goto, help="send a blocked run back to a stage")
    sp.add_argument("run")
    sp.add_argument("stage")

    sp = add("skip", _skip, help="pass a skippable gate")
    sp.add_argument("run")
    sp.add_argument("--gate", required=True)
    sp.add_argument("--reason", required=True)

    sp = add("abort", _abort, help="end a run as aborted")
    sp.add_argument("run")
    sp.add_argument("--reason")

    sp = add("resume", _resume, help="continue a run whose engine died")
    sp.add_argument("run")

    sp = add("recover", _recover, help="close open attempts; --rebuild rewrites run.json")
    sp.add_argument("run")
    sp.add_argument("--rebuild", action="store_true")

    sp = add("status", _status, help="runs and stages in this repo")
    sp.add_argument("run", nargs="?")

    sp = add("where", _where, help="every path of a run")
    sp.add_argument("run")

    sp = add("events", _events, help="a run's recent events")
    sp.add_argument("run")
    sp.add_argument("--tail", type=int, default=50)

    sp = add("usage", _usage, help="token totals per observed model")
    sp.add_argument("run", nargs="?")
    sp.add_argument("--since", help="YYYY-MM-DD")

    sp = add("gc", _gc, help="show, then apply, the housekeeping plan")
    sp.add_argument("--apply", action="store_true")
    return p


def _parse(argv: list[str]) -> argparse.Namespace:
    """Parse argv. `decide` takes its answers anywhere among the options (module 16, decision M1), which argparse
    cannot do with a positional list, so its leftovers are read here: each must be ID=option, or it is a usage error."""
    parser = _parser()
    args, extra = parser.parse_known_args(argv)
    if getattr(args, "handler", None) is None or args.command != "decide":
        if extra:
            parser.error(f"unrecognized arguments: {' '.join(extra)}")
        return args
    bad = [tok for tok in extra if not _ANSWER.fullmatch(tok)]
    if bad:
        parser.error(f"unrecognized arguments: {' '.join(bad)} (answers take the form D1=opt-a)")
    args.answers = [*args.answers, *extra]
    return args


_ANSWER = re.compile(r"[A-Za-z][\w-]*=[^\s]+")


def main(argv: list[str] | None = None, *, worker_factory=None, tracker_factory=None, prs_factory=None,
         command_factory=None) -> int:
    """Run one command and return its exit code. `python -m factory_engine` raises it as SystemExit."""
    argv = sys.argv[1:] if argv is None else list(argv)
    _WANTS_JSON["on"] = "--json" in argv
    args = _parse(argv)
    f = Factories(worker_factory=worker_factory, tracker_factory=tracker_factory, prs_factory=prs_factory,
                  command_factory=command_factory)
    try:
        result = args.handler(args, f)
    except FactoryError as e:
        if args.json:
            _emit_json(False, e.code, e.message, e.hint, {})
        else:
            print(f"{e.code}: {e.message}\nhint: {e.hint}", file=sys.stderr)
        return e.exit_code
    if args.json:
        _emit_json(result.code == EXIT_OK, _code_name(result.code), result.message, result.hint, result.data)
    else:
        print(result.message)
        if result.hint:
            print(f"hint: {result.hint}")
    return result.code


def _code_name(code: int) -> str:
    return {EXIT_OK: "ok", EXIT_FAILED: "failed", EXIT_INVALID: "invalid", EXIT_WAITING_HUMAN: "waiting",
            EXIT_BLOCKED: "blocked"}.get(code, "locked" if code == 5 else "unknown")
