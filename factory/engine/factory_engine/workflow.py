"""Workflows (module 5): load a workflow file, validate it, and expand helper tasks.

Lookup is .factory/config/workflows/<name>.yaml, then factory/workflows/<name>.yaml (the kit the run uses). Plugins
are phase 1b and are not applied here. Every problem found at load stops the run before a worker starts.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Literal

import jsonschema
import yaml

from . import skills
from .config import Config
from .errors import FactoryError
from .skills import resolve_skill
from .types import (Defaults, GateSpec, HelperPolicy, OnFail, Policy, Problem, Stage, TaskSpec, Workflow)
from .validate import SCHEMA_DIR
from .yamlio import FactoryLoader, load_yaml

NAME_PATTERN = re.compile(r"^_?[a-z][a-z0-9_-]*$")

# Module 8's check names (its CHECKS table). Module 5 reads them without importing gates.py, so the list lives here
# until that module lands; known_checks in gates.py then replaces it.
KNOWN_CHECKS = frozenset({
    "scope-diff", "helpers-ledger", "type-resolved", "decision-approved", "packet-hash-matches",
    "no-blocking-findings", "evidence-cites-code", "every-claim-has-source", "lint-clean", "build-matches-stack",
})


def load_workflow(repo: Path, cfg: Config, name: str) -> Workflow:
    """Lookup .factory/config/workflows, then the kit's workflows; parse; validate; check skill names.

    Raises config.invalid listing every problem, with the file and the path inside it. Nothing starts on a failure.
    """
    if not NAME_PATTERN.fullmatch(name):
        raise FactoryError("config.invalid", f"workflow name {name!r} must be lower-case letters, digits and hyphens",
                           hint="pass the workflow's file name without .yaml, such as bug-fix")
    path = _find(repo, name)
    text = path.read_text()
    doc = load_yaml(text, file=str(path))
    if not isinstance(doc, dict):
        _raise([Problem(str(path), None, "the top level must be a mapping", "write the workflow keys at the top level")])

    problems = _schema_problems(doc, text, str(path))
    if problems:
        _raise(problems)

    wf = _parse(doc, name)
    problems = [replace(p, file=str(path)) for p in validate_workflow(wf, cfg)]
    if wf.name != name:
        problems.append(Problem(str(path), None, f"name: {wf.name!r} does not match the file name {name!r}",
                                f"set name: {name}"))
    problems += _skill_problems(wf, repo, cfg, str(path))
    if problems:
        _raise(problems)
    return wf


def validate_workflow(wf: Workflow, cfg: Config) -> list[Problem]:
    """Semantic checks on a parsed workflow: needs cycles, unknown stages, tasks and checks, goto targets, quorum,
    overlapping write scopes and shared_files owners. Skill names need the repo, so load_workflow checks them.

    Problem.file holds the workflow name here; load_workflow replaces it with the file it read. cfg is not needed for
    these checks; it is in the signature the spec declares.
    """
    return _semantic_problems(wf)


def _semantic_problems(wf: Workflow) -> list[Problem]:
    problems: list[Problem] = []

    def bad(where: str, message: str, hint: str) -> None:
        problems.append(Problem(wf.name, None, f"{where}: {message}", hint))

    for sid in _duplicates([s.id for s in wf.stages]):
        bad("stages", f"stage id {sid!r} is used twice", "give each stage a unique id")
    task_ids = [t.id for s in wf.stages for t in s.tasks]
    for tid in _duplicates(task_ids):
        bad("stages", f"task id {tid!r} is used twice", "give each task a unique id across the workflow")

    stages = {s.id: s for s in wf.stages}
    stage_graph: dict[str, list[str]] = {}
    for s in wf.stages:
        where = f"stages.{s.id}"
        for n in s.needs:
            if n not in stages:
                bad(f"{where}.needs", f"unknown stage {n!r}", "name a stage id from this workflow")
        stage_graph[s.id] = [n for n in s.needs if n in stages]
        for path, goto in _gotos(s):
            if goto not in stages:
                bad(path, f"goto {goto!r} is not a stage in this workflow", "name a stage id from this workflow")
    cycle = _cycle(stage_graph)
    if cycle:
        bad("stages", "needs cycle: " + " -> ".join(cycle), "remove one needs entry on the cycle")

    task_graphs: dict[str, dict[str, list[str]]] = {}
    for s in wf.stages:
        where = f"stages.{s.id}"
        local = {t.id for t in s.tasks}
        graph = {}
        for t in s.tasks:
            for n in t.needs:
                if n not in local:
                    bad(f"{where}.tasks.{t.id}.needs", f"unknown task {n!r} in stage {s.id!r}",
                        "task order runs inside one stage; name a task of this stage")
            graph[t.id] = [n for n in t.needs if n in local]
            if (t.skill is None) == (t.cmd is None):
                bad(f"{where}.tasks.{t.id}", "set exactly one of skill and cmd",
                    "skill runs a worker; cmd runs a command without an LLM")
        task_graphs[s.id] = graph
        cycle = _cycle(graph)
        if cycle:
            bad(where, "tasks needs cycle: " + " -> ".join(cycle), "remove one needs entry on the cycle")
        for g in s.gate:
            if g.kind == "check" and g.check not in KNOWN_CHECKS:
                bad(f"{where}.gate", f"unknown check {g.check!r}",
                    "use a check from module 8: " + ", ".join(sorted(KNOWN_CHECKS)))
        if s.join.startswith("quorum:") and int(s.join.split(":", 1)[1]) > len(s.tasks):
            bad(f"{where}.join", f"{s.join} needs more tasks than stage {s.id!r} has",
                "lower N or add tasks")

    for key, owner in wf.shared_files.items():
        if owner not in task_ids:
            bad(f"shared_files.{key}", f"owner {owner!r} is not a task in this workflow", "name a task id as the owner")

    problems += _scope_problems(wf, stage_graph, task_graphs)
    return problems


def expand_tasks_from(stage: Stage, artifact: Path) -> list[TaskSpec]:
    """One task per item of the JSON array in `artifact`, each in the workflow's task form (module 5).

    Every item is checked against the workflow schema's task definition before any task is returned, so a bad item
    stops the stage before a worker starts. The error names the item's index and the path inside it.
    """
    where = f"{artifact} (stage {stage.id})"
    try:
        items = json.loads(artifact.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise FactoryError("config.invalid", f"{where}: cannot read the generated task list: {e}",
                           hint="the earlier task must write a JSON array of task objects") from e
    if not isinstance(items, list):
        raise FactoryError("config.invalid", f"{where}: the generated task list must be a JSON array",
                           hint="write a JSON array with one task object per item")
    schema = _task_schema()
    validator = jsonschema.Draft202012Validator(schema)
    for i, item in enumerate(items):
        for e in sorted(validator.iter_errors(item), key=lambda e: list(e.absolute_path)):
            path = _dotted(list(e.absolute_path))
            raise FactoryError("config.invalid", f"{where}: item {i}: {path}: {e.message}",
                               hint="fix the generated task so it matches the workflow task form")
    tasks = [_parse_task(item, Defaults(**DEFAULTS)) for item in items]
    # The generated tasks form one stage of their own, so the same checks as a static stage apply to them.
    as_stage = Stage(id=stage.id, needs=[], tasks=tasks, tasks_from=None, join="all", gate=[], on_fail=None,
                     on_conflict=None, approval="none", on_reject=None, sync_base=False, source=stage.source)
    as_workflow = Workflow(name=stage.id, type="generated", sink="comment", policy=Policy(write=False, deny_paths=[]),
                           defaults=Defaults(**DEFAULTS), stages=[as_stage], regenerate_at_join=[], join_cmd=None,
                           shared_files={})
    problems = _semantic_problems(as_workflow)
    if problems:
        raise FactoryError("config.invalid", f"{where}: " + "; ".join(p.message for p in problems),
                           hint=problems[0].hint)
    return tasks


def expand_helpers(task: TaskSpec, subagents: Literal["native", "none"]) -> list[TaskSpec]:
    """The task itself when the harness can split natively, else one sibling task per split hint (module 5, module 9).

    Siblings get the parent's scope and needs, helpers off, and an artifact named after the hint, so the stage has
    the same shape with helpers off as with them on. A task with no split hints is returned unchanged.
    """
    if subagents == "native" and task.helpers.mode != "off":
        return [task]
    return [
        replace(task, id=f"{task.id}-{hint}", out=_sibling_out(task.out, hint),
                helpers=HelperPolicy(mode="off", max=0, split_hints=[], timeout_minutes=task.helpers.timeout_minutes))
        for hint in task.helpers.split_hints
    ] or [task]


def _task_schema() -> dict:
    """The workflow schema's task definition, with its $defs, so internal references still resolve."""
    schema = json.loads((SCHEMA_DIR / "workflow.schema.json").read_text())
    return {"$ref": "#/$defs/task", "$defs": schema["$defs"]}


def _find(repo: Path, name: str) -> Path:
    for root in (repo / ".factory" / "config" / "workflows", skills.KIT / "workflows"):
        candidate = root / f"{name}.yaml"
        if candidate.is_file():
            return candidate
    raise FactoryError("config.invalid", f"no workflow named {name!r}",
                       hint=f"add .factory/config/workflows/{name}.yaml, or use a built-in workflow name")


def _raise(problems: list[Problem]) -> None:
    message = "\n".join(f"{p.file}{'' if p.line is None else f':{p.line}'}: {p.message}" for p in problems)
    raise FactoryError("config.invalid", message, hint=problems[0].hint)


def _schema_problems(doc: dict, text: str, file: str) -> list[Problem]:
    string_cmds = _string_commands(doc)
    problems = [Problem(file, _line_at(text, path), f"{_dotted(path)}: a command is a string",
                        "write the command as a list, such as cmd: [make, test]") for path in string_cmds]
    schema = json.loads((SCHEMA_DIR / "workflow.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        path = list(e.absolute_path)
        if path in string_cmds:
            continue  # reported above with the list form to write
        problems.append(Problem(file, _line_at(text, path), f"{_dotted(path)}: {e.message}",
                                f"fix {_dotted(path)} to match factory/schemas/workflow.schema.json"))
    return problems


def _string_commands(node, path: tuple = ()) -> list[list]:
    """Paths of every cmd or join_cmd written as a string. Commands are lists, never shell strings (module 18)."""
    found: list[list] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = [*path, key]
            if key in ("cmd", "join_cmd") and isinstance(value, str):
                found.append(here)
            else:
                found += _string_commands(value, here)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found += _string_commands(value, [*path, i])
    return found


def _line_at(text: str, path: list) -> int:
    """The line of the node at this path, or of the nearest parent that exists."""
    node = yaml.compose(text, Loader=FactoryLoader)
    for seg in path:
        if isinstance(node, yaml.MappingNode):
            child = next((v for k, v in node.value if k.value == str(seg)), None)
        elif isinstance(node, yaml.SequenceNode) and isinstance(seg, int) and seg < len(node.value):
            child = node.value[seg]
        else:
            child = None
        if child is None:
            break
        node = child
    return node.start_mark.line + 1


def _dotted(path: list) -> str:
    return ".".join(str(p) for p in path) or "(top level)"


# The values the spec's bug-fix example gives under defaults. A workflow that omits a key gets these.
DEFAULTS = {"retries": 2, "timeout_minutes": 30, "checkpoint_every_minutes": 10, "max_restarts": 3}


def _parse(doc: dict, name: str) -> Workflow:
    """A file may omit name, type, sink, policy and defaults, as the spec's _triage example does.

    type defaults to the name. policy.write defaults to false, a detached worktree, the safe choice. sink defaults to
    pull_request for a workflow that writes and to comment for one that does not, since a read-only run answers only."""
    defaults = Defaults(**{**DEFAULTS, **doc.get("defaults", {})})
    policy = {"write": False, **doc.get("policy", {})}
    sink = doc.get("sink", "pull_request" if policy["write"] else "comment")
    return Workflow(
        name=doc.get("name", name), type=doc.get("type", name), sink=sink,
        policy=Policy(write=policy["write"], deny_paths=list(policy.get("deny_paths", []))),
        defaults=defaults,
        stages=[_parse_stage(s, defaults) for s in doc["stages"]],
        regenerate_at_join=list(doc.get("regenerate_at_join", [])),
        join_cmd=doc.get("join_cmd"),
        shared_files=dict(doc.get("shared_files", {})),
    )


def _parse_stage(s: dict, defaults: Defaults) -> Stage:
    return Stage(
        id=s["id"],
        needs=list(s.get("needs", [])),
        tasks=[_parse_task(t, defaults) for t in s.get("tasks", [])],
        tasks_from=s.get("tasks_from"),
        join=s.get("join", "all"),
        gate=[_parse_gate(g) for g in s.get("gate", [])],
        on_fail=_parse_goto(s.get("on_fail")),
        on_conflict=_parse_goto(s.get("on_conflict")),
        approval=s.get("approval", "none"),
        on_reject=(s.get("on_reject") or {}).get("goto"),
        sync_base=s.get("sync_base", s["id"] == "verify"),
        source="workflow",
    )


def _parse_task(t: dict, defaults: Defaults) -> TaskSpec:
    h = t.get("helpers") or {}
    # A deterministic task (cmd, no skill) gives the same answer on a rerun, so it gets no retries by default (module 5).
    default_retries = 0 if t.get("skill") is None else defaults.retries
    return TaskSpec(
        id=t["id"],
        skill=t.get("skill"),
        cmd=t.get("cmd"),
        run=None,
        scope=list(t.get("scope", [])),
        deny=list(t.get("deny", [])),
        needs=list(t.get("needs", [])),
        helpers=HelperPolicy(mode=h.get("mode", "off"), max=h.get("max", 0),
                             split_hints=list(h.get("split_hints", [])), timeout_minutes=h.get("timeout_minutes")),
        out=t.get("out"),
        timeout_minutes=t.get("timeout_minutes", defaults.timeout_minutes),
        retries=t.get("retries", default_retries),
        model=t.get("model"),
        when=t.get("when"),
    )


def _parse_gate(g: dict) -> GateSpec:
    skippable = g.get("skippable", False)
    if "cmd" in g:
        return GateSpec(kind="cmd", cmd=list(g["cmd"]), check=None, schema=None, args={}, skippable=skippable)
    if "check" in g:
        return GateSpec(kind="check", cmd=None, check=g["check"], schema=None, args={}, skippable=skippable)
    return GateSpec(kind="schema", cmd=None, check=None, schema=g["schema"], args={}, skippable=skippable)


def _parse_goto(node: dict | None) -> OnFail | None:
    return None if node is None else OnFail(goto=node["goto"], max=node["max"])


def _gotos(s: Stage) -> list[tuple[str, str]]:
    out = []
    if s.on_fail:
        out.append((f"stages.{s.id}.on_fail.goto", s.on_fail.goto))
    if s.on_conflict:
        out.append((f"stages.{s.id}.on_conflict.goto", s.on_conflict.goto))
    if s.on_reject:
        out.append((f"stages.{s.id}.on_reject.goto", s.on_reject))
    return out


def _cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """One cycle as a path that starts and ends at the same node, or None."""
    state: dict[str, int] = {}  # 1 on the current path, 2 finished
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        path.append(node)
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                return path[path.index(nxt):] + [nxt]
            if nxt not in state:
                found = visit(nxt)
                if found:
                    return found
        path.pop()
        state[node] = 2
        return None

    for node in graph:
        if node not in state:
            found = visit(node)
            if found:
                return found
    return None


def _reach(graph: dict[str, list[str]], start: str) -> set[str]:
    seen: set[str] = set()
    todo = list(graph.get(start, []))
    while todo:
        node = todo.pop()
        if node not in seen:
            seen.add(node)
            todo.extend(graph.get(node, []))
    return seen


def _scope_problems(wf: Workflow, stage_graph: dict[str, list[str]],
                    task_graphs: dict[str, dict[str, list[str]]]) -> list[Problem]:
    """Two tasks that can run together must not write overlapping scopes, unless a shared_files entry covers both."""
    stage_reach = {sid: _reach(stage_graph, sid) for sid in stage_graph}

    def ordered(s1: Stage, t1: TaskSpec, s2: Stage, t2: TaskSpec) -> bool:
        if s1.id == s2.id:
            graph = task_graphs[s1.id]
            return t2.id in _reach(graph, t1.id) or t1.id in _reach(graph, t2.id)
        return s2.id in stage_reach[s1.id] or s1.id in stage_reach[s2.id]

    flat = [(s, t) for s in wf.stages for t in s.tasks]
    problems = []
    for i, (s1, t1) in enumerate(flat):
        for s2, t2 in flat[i + 1:]:
            if not t1.scope or not t2.scope or ordered(s1, t1, s2, t2):
                continue
            for p in t1.scope:
                for q in t2.scope:
                    if _uncovered_overlap(p, q, wf.shared_files):
                        problems.append(Problem(
                            wf.name, None,
                            f"stages.{s1.id}.tasks.{t1.id} and stages.{s2.id}.tasks.{t2.id} can run together and "
                            f"write overlapping scopes {p!r} and {q!r}",
                            "add needs between the two tasks, or name the shared file in shared_files"))
    return problems


def _uncovered_overlap(p: str, q: str, shared: dict[str, str]) -> bool:
    """True when the two patterns can match the same file and that file is not listed in shared_files.

    A literal path has one possible file, so it is exact: it overlaps when equal or when the glob matches it, and
    shared_files covers it by name. Two globs can match many files, which one shared_files entry cannot cover, so a
    glob-to-glob overlap is always reported (the fix is needs, or splitting the scopes). This may report an overlap
    no real file has (src/*.py and src/*.ts), never misses one.
    """
    if _literal(p) and _literal(q):
        return p == q and p not in shared
    if _literal(p):
        return fnmatch.fnmatchcase(p, q) and p not in shared
    if _literal(q):
        return fnmatch.fnmatchcase(q, p) and q not in shared
    a, b = _literal_prefix(p), _literal_prefix(q)
    n = min(len(a), len(b))
    return a[:n] == b[:n]


def _literal(pattern: str) -> bool:
    return not any(c in pattern for c in "*?[")


def _literal_prefix(pattern: str) -> list[str]:
    segments = []
    for seg in pattern.split("/"):
        if not _literal(seg):
            break
        segments.append(seg)
    return segments


def _duplicates(items: list[str]) -> list[str]:
    seen, dup = set(), []
    for item in items:
        if item in seen and item not in dup:
            dup.append(item)
        seen.add(item)
    return dup


def _skill_problems(wf: Workflow, repo: Path, cfg: Config, file: str) -> list[Problem]:
    problems = []
    for s in wf.stages:
        for t in s.tasks:
            if t.skill is None:
                continue
            try:
                resolve_skill(t.skill, repo, cfg)
            except FactoryError as e:
                problems.append(Problem(file, None, f"stages.{s.id}.tasks.{t.id}: {e.message}", e.hint))
    return problems


def _sibling_out(out: str | None, hint: str) -> str | None:
    if out is None:
        return None
    base, dot, ext = out.rpartition(".")
    if not dot:
        return f"{out}-{hint}"
    return f"{base}-{hint}.{ext}"
