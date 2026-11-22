# 5. Module: workflows and plugins

Part of the [phase 1 design](../phase-1.md#module-map). Build wave: 2. Contracts and acceptance criteria are in this file; shared types are in [section 18](../shared/18-shared-contracts.md). Terms such as run, stage, task, attempt and rework are defined in the [glossary](../phase-1.md#2-glossary).

A workflow is a YAML list of stages; each stage holds parallel tasks, a join rule, gates and what happens on failure or rejection. Plugins insert stages, tasks or gates without editing workflow files.

```yaml
name: bug-fix
type: bug                         # request type that selects this workflow
sink: pull_request                # pull_request | doc | comment
policy:
  write: true                     # false: detached worktree; a branch only at delivery into the repo
  deny_paths: [".github/**"]
defaults:
  retries: 2                      # extra attempts after a worker error
  timeout_minutes: 30
  checkpoint_every_minutes: 10
  max_restarts: 3                 # note-driven restarts per task
stages:
  - id: fix
    needs: [propose]              # stage order
    tasks:
      - id: backend
        skill: fix                # resolved through stages.map.yaml
        scope: ["services/api/**"]
        needs: []                 # task order inside the stage
        helpers: {mode: auto, max: 2, split_hints: [api-code, tests]}   # auto | native | off
        out: backend.json         # must match schemas/stage-report
    join: all                     # all | any | quorum:N
    gate:
      - {cmd: [make, build]}
      - {check: scope-diff}
      - {check: helpers-ledger, skippable: true}   # optional; `factory skip` can pass only a gate marked so
    on_fail: {goto: root-cause, max: 2}     # rework with a feedback record
    on_conflict: {goto: fix, max: 1}        # merge conflict at join
    approval: none                # none | human | when-low-confidence
    on_reject: {goto: propose}    # where a rework answer sends the run
```

**Rules the engine enforces**

- Tasks with no `needs` start together, up to the concurrency limit. A task with `cmd` and no `skill` runs without an LLM.
- Gates run in order and stop at the first failure. Prefer a command or schema check; use an LLM rubric only inside a task whose output a schema gate then reads.
- A gate may carry `skippable: true` (default `false`, and no shipped gate sets it). Only such a gate can be passed by `factory skip` on a blocked run ([module 8](08-gates-error-handling-and-rework.md)). The one exception is `no-test-results`, the T1 block, which module 8 describes. A gate's id is the name its results carry: `cmd: [make, lint]` for a command, `schema: stage-report` for a schema, and the check name (`scope-diff`) for a check.
- `tasks_from` builds a stage's task list from an earlier artifact at run time. The engine validates the generated tasks against the workflow schema before starting them.
- **Join.** Phase 1a code waits for every task of a stage before its join, whatever `join` says. When a task fails for good, no new task starts, the tasks already running finish, and the run is blocked for a person (module 8). Every shipped workflow uses `all`. `any` and `quorum:N` load (`quorum:N` needs N no larger than the stage's task count), but no code acts on them yet. Their phase 1b rule: the join runs once one task (`any`) or N tasks (`quorum:N`) are done. Tasks still running then are stopped, as a timeout stops a task, and their changes are not joined. If so many tasks have failed that N cannot be reached, the stage fails and the run is blocked, as for any failed task.
- With `task_template`, the artifact is a list of plain questions, `[{"id": "q1", "question": "..."}]`, and each task is the template plus the item's own fields; an item may override a template field, such as `timeout_minutes`. The question goes into that task's prompt under "Your question". The template is checked as a task when the workflow loads, so a bad template fails before any run starts. A question list on a stage with no `task_template` is refused, and so is `task_template` on a stage with no `tasks_from` (owner decision, 2026-11-21).
- Lookup order: `.factory/config/workflows/`, then `factory/workflows/`. The built-in workflows, their phases and where each is specified are in the table under **Built-in workflows and scope**, below.
- A workflow file is checked against `factory/schemas/workflow.schema.json`. Only `stages` is required. A file that omits keys gets these values: `name` from the file name, `type` from the name, `policy.write: false`, `sink: pull_request` when it writes and `comment` when it does not, and the `defaults` values in the example above. A task with `cmd` and no `skill` gets `retries: 0` unless it sets its own. A task may set `max_interruptions`, an integer of 0 or more, default 3. Its Nth interruption by an engine crash fails it, so with 3 the third crash fails the task and two still resume ([module 8](08-gates-error-handling-and-rework.md)).
- A stage with `verify` as its id has `sync_base: true` unless the file says otherwise.
- `load_workflow` reports every problem it finds in one `config.invalid` error, each with the file, the line where the YAML has one, and the path inside the file. It also resolves each task's `skill` through module 10. `validate_workflow` takes no repo, so it does not check skill names.
- Two parallel tasks overlap when their scopes can match the same file. A listed file in `shared_files` clears an overlap only when it is the one file the two scopes share. Two glob scopes that overlap are always reported, because one listed file cannot cover every file they match.

**Built-in workflows and scope**

In phase 1a this module builds loading, validation, `expand_tasks_from` and `expand_helpers`. The engine runs the three shipped workflows. Plugins, hooks, plugin `when` and `tasks_from` for plugins are phase 1b, and so are feature, new-app and research ([phase split](../phase-1.md#phase-split)). The research example below is described only so its shape can be built; no shipped file exists for it.

| Workflow | Phase | Shipped file | Where it is specified |
| --- | --- | --- | --- |
| `_triage` | 1a | `factory/workflows/_triage.yaml` | [module 4](04-intake-and-triage.md), which holds its YAML and the triage stop |
| bug-fix | 1a | `factory/workflows/bug-fix.yaml` | This file, the example below; the failure classes in [module 8](08-gates-error-handling-and-rework.md) |
| chore | 1a | `factory/workflows/chore.yaml` | This file, the example below |
| feature | 1b | none | No stage list. [Module 11](11-human-stops.md) gives an architecture stage that feature runs when a rule fires; [modules 3](03-kit-and-configuration.md) and [13](13-delivery.md) only name it |
| new-app | 1b | none | No stage list. [Module 11](11-human-stops.md) gives its architecture stage, which always runs |
| research | 1b | none | This file, the example below (illustrative) |
| reviewer-eval | phase 2 | `factory/workflows/reviewer-eval.yaml`, shipped in the kit | Not in this file. It is phase 2 work that stayed on main. It is its own workflow, not a stage in `bug-fix.yaml`: nothing starts it except a person who runs the eval by hand |

**Bug-fix workflow**

```yaml
name: bug-fix
type: bug
sink: pull_request
stages:
  - id: reproduce
    tasks: [{id: repro, skill: reproduce, out: repro.json}]
    gate: [{cmd: [scripts/repro-fails.sh]}]          # a failing test must exist
  - id: root-cause
    needs: [reproduce]
    tasks: [{id: cause, skill: root-cause, out: cause.json}]
    gate: [{schema: stage-report}, {check: evidence-cites-code}]
  - id: propose
    needs: [root-cause]
    tasks: [{id: plan, skill: propose, out: plan.json}]
    approval: human
    on_reject: {goto: root-cause}
  - id: fix
    needs: [propose]
    tasks:
      - {id: backend, skill: fix, scope: ["services/api/**"],
         helpers: {mode: auto, max: 2, split_hints: [api-code, tests]}, out: backend.json}
      - {id: frontend, skill: fix, scope: ["web/**"], needs: [backend], out: frontend.json}
    join: all
    gate: [{cmd: [make, build]}, {check: scope-diff}, {check: helpers-ledger}]
    on_fail: {goto: root-cause, max: 2}
  - id: verify
    needs: [fix]
    tasks:
      - {id: be-tests, cmd: [make, test-api], out: be.junit.xml}
      - {id: fe-tests, cmd: [npm, --prefix, web, test], out: fe.junit.xml}
      - {id: e2e, cmd: [make, e2e], needs: [be-tests, fe-tests], out: e2e.junit.xml}
    join: all
    gate: [{cmd: [scripts/repro-now-passes.sh]}, {schema: test-report}]
    on_fail: {goto: fix, max: 3}
  - id: review
    needs: [verify]
    tasks:
      - {id: standards, skill: review-standards, out: standards.json}
      - {id: spec, skill: review-spec, out: spec.json}
    join: all
    gate: [{check: no-blocking-findings}]
    on_fail: {goto: fix, max: 1}
```

The two review tasks replace one skill that would otherwise start two subagents, so the engine sees both. The verify stage has no LLM tasks.

**Chore workflow** (phase 1a)

A chore is a small change with no root-cause analysis and no approval stop. It has one worker task, then the repo's own check, and it has no review stage, so a chore costs one worker run. Its scope is the whole repo except the deny paths. Merge policy ([module 13](13-delivery.md)) decides whether a chore auto-merges.

```yaml
name: chore
type: chore
sink: pull_request
policy: {write: true, deny_paths: [".github/**"]}
stages:
  - id: implement
    tasks: [{id: change, skill: implement, scope: ["**"], helpers: {mode: off}, out: change.json}]
    gate: [{check: scope-diff}, {check: lint-clean}]
    on_fail: {goto: implement, max: 2}
  - id: verify
    needs: [implement]
    tasks: [{id: check, cmd: [scripts/check], out: check.log}]
    on_fail: {goto: implement, max: 2}
```

**Research workflow**

```yaml
name: research
type: research
sink: doc
policy: {write: false}
stages:
  - id: scope
    tasks: [{id: questions, skill: scope, out: questions.json}]
    approval: human                     # you confirm the sub-questions, a plain list such as:
                                        #   [{"id": "q1", "question": "What does the vendor charge per seat?"}]
  - id: gather
    needs: [scope]
    tasks_from: questions.json          # one task per sub-question, in parallel
    task_template: {skill: gather, helpers: {mode: off}, timeout_minutes: 20}   # each question's task starts from this
    join: all
    gate: [{schema: source-notes}]
  - id: synthesize
    needs: [gather]
    tasks: [{id: draft, skill: synthesize, out: report.md}]
  - id: critique
    needs: [synthesize]
    tasks: [{id: red-team, skill: critique, out: critique.json}]
    gate: [{check: every-claim-has-source}]
    on_fail: {goto: synthesize, max: 1}
```

**Plugins**

A plugin is a folder in `.factory/config/plugins/` with one manifest. `factory plugins enable <name>` validates it and prints the merged workflow.

```yaml
# .factory/config/plugins/frontend-review/plugin.yaml
name: frontend-review
version: 0.1.0
requires: {skills: [impeccable]}         # must be in skills.lock
applies_to: [feature, bug-fix, new-app]
when: {changed_paths: ["web/**"]}        # skipped if no UI files changed
insert:
  after: verify
  stage:
    id: frontend-review
    tasks:
      - {id: design-audit, skill: impeccable-audit, scope: ["web/**"], helpers: {mode: off}, out: audit.json}
      - {id: design-critique, skill: impeccable-critique, scope: ["web/**"], helpers: {mode: off}, out: critique.json}
    join: all
    gate: [{schema: review-findings}, {check: no-blocking-findings}]
    on_fail: {goto: fix, max: 2}
```

- **Hook points.** A plugin can insert a stage before or after a named stage (`insert`, which `plugin.schema.json` has), add a task to a stage, add a gate to a stage, or replace a task's skill. The last three have no keys in `plugin.schema.json` yet, so the schema must gain them before a manifest may use them. Phase 1b syntax: `add_task: {stage: <id>, task: {...}}`, `add_gate: {stage: <id>, gate: {...}}` and `replace_skill: {stage: <id>, task: <id>, skill: <name>}`. An added task or gate goes after the stage's existing ones. `replace_skill` changes a task's skill, because a stage has no skill of its own.
- **`when`.** The engine evaluates only `confidence_below` today (triage, `_when_holds`). Any other key holds, so a `changed_paths` condition is not enforced in phase 1a. In phase 1b, `when: {changed_paths: [...]}` on a task is checked when the task is due to start, against the files the run branch changes from its base. That is the diff the scope check reads (`gitops.changed_files`). If no changed file matches any glob, the task is skipped: it is recorded as done with no attempts, as `_skip_task` records a skipped task. A manifest-level `when` is checked when the run reaches the inserted stage. If it does not hold, the stage is marked skipped and none of its tasks or gates run.
- Plugins apply in file order and never edit workflow files. Each added stage records its source, such as `plugin:frontend-review`, in `run.json`.
- A plugin applies only to the workflows its `applies_to` names, by workflow name (`bug-fix`), not by the `type` key (`bug`). Its `goto` must name a stage in each of them. Phase 1b runs the goto check of `validate_workflow` on the merged workflow, so a plugin stage whose `goto` names a missing stage fails the load with `config.invalid` at `stages.<id>.on_fail.goto`, before any worker starts.
- The gate reads only the findings JSON, so free-form skill output never decides pass or fail. Impeccable needs a one-time design context per repo, listed as a plugin setup step; check its license and command names before pinning.

**Report schemas**

The spec gave no fields to four report schemas, so a gate that names one could not run. Wave 3 drafted them in `factory/schemas/`, and the owner accepted the drafts as the phase 1 schemas (wave 3, decision D1). They are the smallest shape the skills and gates need. Real model output has not been run against them yet, so the first live run may show a field to change; change the schema and its tests together.

| Schema | Written by | Fields | Read by |
| --- | --- | --- | --- |
| `stage-report` | reproduce, root-cause, propose, fix, implement | `stage`, `summary`; `claims[]` of `claim`, `file`, `line`; optional `files_changed` | `{schema: stage-report}`; `evidence-cites-code` requires at least one claim and checks each cited file and line exists in the worktree |
| `test-report` | the engine, from the verify tasks' JUnit files (`write_test_report`) | `total`, `failed[]` (test names) | `{schema: test-report}` |
| `review-findings` | review-standards, review-spec, critique, plugin reviewers | `findings[]` of `file`, `line`, `severity` (low, medium, high), `rule`, optional `message` | `no-blocking-findings`: a finding of **medium or high** blocks (the owner accepted this; it matches `review_findings_at_or_above: medium` in module 13) |
| `source-notes` | gather | `sources[]` of `address`, `says`, `trust` (free text; no scale is specified) | `{schema: source-notes}`. The check `every-claim-has-source` is still unbuilt, because the spec does not say how a claim is matched to a source |

`questions.json` is a list of plain questions, `{id, question}`, not `source-notes` (owner decision, 2026-11-21). `source-notes` is what each `gather` task writes. The research workflow is phase 1b.

**Deterministic plugin tasks, checks and hooks**

A plugin can add work that runs without any LLM: a command, a script file or a Python function it ships. Each one has a timeout, a log, an artifact and a gate, and costs no tokens. Each one runs under `srt`, with the same read and write rules as a worker (see Safety).

| Kind | In the manifest | How it runs |
| --- | --- | --- |
| Command | `cmd: ["npm", "run", "lint"]` | An argument list, run in the worktree under `srt`. The engine quotes each element, so none is read as shell syntax |
| Script | `run: {script: scripts/scan_licenses.py, args: [...]}` | The script path is taken from the plugin folder, and the worktree is the working folder. Under `srt`, `.py` runs with the engine's Python, an executable file runs directly, and `.sh` runs with `sh`. `.ps1` is Windows only, so it is phase 2. `os:` says where the script may run |
| Python function | `run: {python: checks.licenses:scan}` | Imported from the plugin folder in a separate Python process under `srt`, using the engine's Python |
| Skill | `skill: impeccable-audit` | An LLM worker, as before |

```yaml
# .factory/config/plugins/license-check/plugin.yaml
name: license-check
version: 0.1.0
applies_to: [bug-fix]                     # goto fix exists only in bug-fix
os: [linux, macos, windows]               # where its scripts may run
insert:
  after: verify
  stage:
    id: license-check
    tasks:
      - id: scan
        run: {script: scripts/scan_licenses.py, args: ["--out", "licenses.json"]}
        out: licenses.json
        timeout_minutes: 5
    gate:
      - {schema: plugin:license-check/report}                 # plugin-shipped JSON Schema
      - {check: plugin:license-check/no-forbidden-licenses}   # function in gates/
    on_fail: {goto: fix, max: 1}
hooks:
  - on: [pr_opened, run_done]
    run: {script: hooks/post_to_teams.py}  # side effect only, never blocks the run
```

**The contract a deterministic task follows**

- **Inputs.** Environment variables `FACTORY_RUN_ID`, `FACTORY_STAGE`, `FACTORY_TASK_ID`, `FACTORY_WORKTREE` and `FACTORY_TASK_DIR`. A Python function also gets the same values as JSON on stdin.
- **Outputs.** Its artifact goes in `FACTORY_TASK_DIR`; stdout and stderr go to `worker.log`. A Python function returns its result as JSON on stdout.
- **Exit codes** depend on the kind of task:
  - **`cmd` tasks** (and gate commands) wrap tools the factory does not control, such as `make`, `npm` and `pytest`, whose exit codes vary. The engine first checks that the binary exists and starts. After that, 0 means passed and any non-zero exit means the check failed, so the stage's `on_fail` rework applies. A missing binary, a timeout or a kill by signal is a task error.
  - **Plugin `script` and `python` tasks** are written to this contract: 0 passed; 1 the check found a problem, so `on_fail` rework applies; 2 or higher the task itself failed, a worker error retried up to `retries`.
  - A task error in a deterministic task defaults to 0 retries, because a rerun gives the same answer
- **Working folder.** The worktree; nothing is written outside it and `FACTORY_TASK_DIR`.
- **Checks.** A plugin check gets the `GateContext` as JSON on stdin and prints a `GateResult` as JSON. It runs in a separate process, so a faulty plugin cannot break the engine.
- **Hooks.** A hook runs after the named event, with the event as JSON on stdin. A failing hook is logged and never stops or changes the run.
- **Failures.**
  - *Invalid stdin.* A Python function reads its context as JSON on stdin. Input that is not JSON is a task error (exit 2), and the function is not called.
  - *Raised error or bad import.* The rule is: exit 1 is only for a check that ran and found a problem. Anything that stops the plugin from running to a result is a task error (exit 2). That covers a function that raises, a function that calls `sys.exit`, a module or function that does not exist, a syntax error in the module, and any other error raised, or `sys.exit` called, while the module is imported. The message goes to stdout, and so to `worker.log`.
  - *Bad result.* A check returns a GateResult as JSON. `passed: false` is a check failure (exit 1), and `passed: true` passes (exit 0). A result dict may also carry a `status` of `passed` (exit 0) or `check_failed` (exit 1), and `status` wins over `passed`. Any other `status` is a task error (exit 2). A result that is neither a dict nor a bool, or that cannot be written as JSON, is a task error (exit 2). A bool maps true to 0 and false to 1.
  - *Timeout.* The engine kills the task's process group at its `timeout_minutes`, and the attempt is a worker error. A deterministic task has 0 retries by default, so the task fails and the run is blocked for a person (module 8).
  - *Hook.* A hook that fails or times out is logged, and the run carries on. A hook is killed after 10 minutes. No manifest key sets that limit in phase 1.

**Safety**

- `factory plugins enable` lists every command, script and function the plugin will run, then records a hash of the plugin folder in `$FACTORY_HOME/plugin-hashes.json`, keyed by repo key. The hash is never stored in the repo, so a commit cannot approve its own plugin change.
- If any plugin file changes later, the plugin is switched off until enabled again, so reviewed code is the code that runs. The hash is checked when a run's snapshot is made (module 3), not while a run goes. A run already in flight keeps its snapshot and finishes with the reviewed code. A run whose snapshot is made after a change finds the hash changed, so the plugin is off for that run.
- A plugin's commands, scripts, Python functions, checks and hooks run under `srt` with the same read and write rules as a worker (module 9). A plugin check is a Python function, so it is covered by the same rule. The factory home and the credential folders cannot be read, and writes reach only the worktree and the task folder. Network is denied, because no workflow or plugin key lists a domain yet. `srt` is a boundary the factory does not own, so enable only plugins you have read.

**Module contract: 5 Workflows and plugins**

- **Depends on:**
  - 3: `load_config`, `validate`
  - 8: `known_checks`
  - 10: `resolve_skill`, used to fail fast on unknown names
  - 17A: `language_tasks`, which builds one test task per detected language for `tasks_from: languages` in verify (phase 1b)
- **Writes:** nothing at run time; `plugins enable` records the reviewed hash in `$FACTORY_HOME/plugin-hashes.json`.
- **CLI it backs:** `plugins enable`, `plugins disable`.

```python
# workflow.py
def load_workflow(repo: Path, cfg: Config, name: str) -> Workflow
    """Lookup .factory/config/workflows, then factory/workflows; apply plugins; validate."""
def validate_workflow(wf: Workflow, cfg: Config) -> list[Problem]
    """duplicate stage and task ids, needs on unknown or cyclic stages and tasks, a task that does not set exactly one of skill,
    cmd or run (a run task is a plugin task, phase 1b; the phase 1a code checks skill and cmd only), unknown check names, unknown goto targets, a quorum larger than the stage's tasks, overlapping parallel
    write scopes, shared_files owners that are not tasks. Schema and skill names are checked by load_workflow."""
def expand_tasks_from(stage: Stage, artifact: Path) -> list[TaskSpec]   # validated like static tasks
    """artifact is a JSON array with one task object per item. Each item must match the workflow schema's task form,
    and the list must pass the checks of a static stage (needs, cycles, overlapping scopes). With the stage's
    task_template, each item is {id, question} plus any task field it overrides."""
def expand_helpers(task: TaskSpec, subagents: Literal["native", "none"]) -> list[TaskSpec]
    """native: [task]; none or mode off: one sibling task per split hint."""
# plugins.py
def enable_plugin(repo: Path, cfg: Config, name: str) -> Workflow    # returns merged result to show
def disable_plugin(repo: Path, name: str) -> None

# types.py (owned by 18, so 5 and 8 never import each other)
@dataclass
class Workflow: name: str; type: str; sink: str; policy: Policy; defaults: Defaults; stages: list[Stage]
                regenerate_at_join: list[str]; join_cmd: list[str] | None; shared_files: dict[str, str]
@dataclass
class Stage:    id: str; needs: list[str]; tasks: list[TaskSpec]; tasks_from: str | None; join: str
                gate: list[GateSpec]; on_fail: OnFail | None; on_conflict: OnFail | None
                approval: str; on_reject: str | None; sync_base: bool; source: str; task_template: dict | None   # workflow or plugin:<name>; with tasks_from, the fields each question's task starts from
@dataclass
class TaskSpec: id: str; skill: str | None; cmd: list[str] | None; run: RunSpec | None; scope: list[str]; deny: list[str]
                needs: list[str]; helpers: HelperPolicy; out: str | None; timeout_minutes: int
                retries: int; model: str | None; when: dict | None; max_interruptions: int   # 3 when the file omits it
```

- **Fields.** `GateSpec`, `RunSpec`, `OnFail` and `HelperPolicy` are defined in [section 18](../shared/18-shared-contracts.md). `Policy` and `Defaults` are not in section 18, so their fields are these, as in `types.py`:
  - `GateSpec`: `kind` (`cmd`, `check` or `schema`), `cmd`, `check`, `schema`, `args` (empty from a workflow file) and `skippable` (default false).
  - `RunSpec`: exactly one of `script` or `python`, and `args`, a list of strings.
  - `OnFail`: `goto` (a stage id) and `max` (the loop count).
  - `HelperPolicy`: `mode` (`auto`, `native` or `off`), `max`, `split_hints` and `timeout_minutes` (optional). When a task has no `helpers` key, the mode is `off` and the maximum is 0.
  - `Policy`: `write` (a boolean, default false) and `deny_paths` (a list of globs). It is the `policy:` key.
  - `Defaults`: `retries`, `timeout_minutes`, `checkpoint_every_minutes` and `max_restarts`, the `defaults:` key. Each has the value in the example above when a file omits it.
- **Join-time keys.** `regenerate_at_join` lists files that are not joined from task changes, such as lockfiles and generated code. At each join, a task's edits to them are dropped from its diff. `join_cmd` is a command, as a list, that runs once after the last task joins, and only when `regenerate_at_join` is not empty. If it exits 0, the listed files are staged and committed as `chore: regenerate lockfiles at join`. If it exits non-zero, nothing is committed, and the join still succeeds. `shared_files` maps a file to the task that owns it. Load checks that the owner is a task, and a listed file clears the overlap check. The engine does not order the other tasks after the owner, so a workflow that needs that order must also add `needs`.

- **Run and test:** `pytest factory/engine/tests/workflow` against the five built-in workflows and broken fixtures; `factory plugins enable frontend-review --json`.
- **Errors:** all fail fast at load or enable; no run starts on an invalid workflow.

Acceptance criteria:

- [ ] All built-in workflows and `_triage` load without problems. (not ticked: test_built_in_workflow_loads_without_problems covers `_triage`, bug-fix and chore, the three that ship in phase 1a; the built-in feature, new-app and research workflows are phase 1b and have no file in `factory/workflows/` to load, so "all" is not yet testable)
- [x] A cycle in `needs`, an unknown skill, an unknown check or an unknown `goto` stage are each reported with their path. (test: factory/engine/tests/workflow/test_workflow.py::test_a_needs_cycle_between_stages_is_reported_with_its_path, ::test_a_needs_cycle_between_tasks_is_reported_with_its_stage, ::test_an_unknown_skill_is_reported_with_its_path, ::test_an_unknown_check_is_reported_with_its_path, ::test_an_unknown_goto_is_reported_with_its_path)
- [x] Two tasks that can run together with overlapping write scopes fail unless one `needs` the other or the file is in `shared_files`. (test: factory/engine/tests/workflow/test_workflow.py::test_two_parallel_tasks_with_overlapping_scopes_fail, ::test_a_needs_between_the_tasks_lifts_the_overlap, ::test_a_literal_file_in_shared_files_is_exempt)
- [ ] A plugin inserts its stage at the right place, records `plugin:<name>` as source, and never edits a workflow file. (not ticked: plugins are phase 1b; no plugin loader exists and tests/workflow has no plugin test)
- [x] `expand_helpers` returns sibling tasks for `none` and the task itself for `native`. (test: factory/engine/tests/workflow/test_workflow.py::test_expand_helpers_native_returns_the_task_itself, ::test_expand_helpers_none_returns_one_sibling_per_hint)
- [x] Tasks from `tasks_from` failing the schema stop the stage before any worker starts. (test: factory/engine/tests/workflow/test_workflow.py::test_generated_tasks_that_fail_the_workflow_schema_are_refused; the check is expand_tasks_from, which raises config.invalid before returning any task, so no worker can start from a bad list; the stage loop that calls it is module 6B and is not merged)
- [x] With `task_template`, each plain question becomes one task built from the template, an item can override a template field, the question reaches that task's prompt, and a bad template fails when the workflow loads. (test: factory/engine/tests/workflow/test_workflow.py::test_each_plain_question_becomes_a_task_built_from_the_template, ::test_a_question_can_override_a_template_setting, ::test_a_question_list_with_no_template_is_refused_with_the_fix_named, ::test_a_templated_question_with_no_question_text_is_refused, ::test_the_spec_research_stage_with_a_task_template_loads, ::test_a_template_that_is_not_a_valid_task_is_refused_when_the_workflow_loads, ::test_a_template_on_a_stage_without_tasks_from_is_refused; factory/engine/tests/workers/test_prompt_and_ledger.py::test_a_task_built_from_a_question_list_shows_its_question_in_the_prompt. No engine-level test runs a templated stage: the engine reads the artifact at `tasks/<tasks_from>`, not where the scope task writes it, see tasks.md item 22)
- [ ] A plugin task with `cmd`, `script` or `python` runs without an LLM, writes its artifact and log, and follows the exit code rules. (not ticked: plugin tasks are phase 1b; the exit rules of the Python runner are tested in test_plugin_runner.py, but no test runs a plugin cmd, script or python task through the engine to its artifact and log)
- [ ] A plugin whose files changed after `enable` is switched off with a message naming the changed file. (not ticked: plugin enable and file hashing are phase 1b; no test)
- [ ] A `.sh` script on a system not listed in `os:` fails the workflow at load, not mid-run. (not ticked: plugin scripts and the os: key are phase 1b; no test or loader check for .sh scripts)
- [ ] A failing hook is logged and the run carries on unchanged. (not ticked: hooks are phase 1b; no test)
- [x] A plugin Python function that raises is a task error (exit 2). (test: factory/engine/tests/workers/test_plugin_runner.py::test_a_function_that_raises_is_a_task_error, factory/engine/tests/workers/test_command_adapter.py::test_a_plugin_function_that_raises_is_a_task_error)
- [x] A plugin that cannot be loaded, whether by a syntax error, any other error at import or a `sys.exit`, is a task error (exit 2). (test: factory/engine/tests/workers/test_plugin_runner.py::test_a_syntax_error_at_import_is_a_task_error, ::test_any_other_error_raised_at_import_is_a_task_error)
- [x] A plugin result with `passed: false` and no `status` is a check failure (exit 1), and a result that cannot be written as JSON is a task error (exit 2). (test: factory/engine/tests/workers/test_plugin_runner.py::test_a_result_with_passed_false_and_no_status_is_a_check_failure, ::test_a_result_that_cannot_be_written_as_json_is_a_task_error)
- [ ] A workflow whose `join` is `quorum:N` with N above the stage's task count is refused at load. (not ticked: a test exists, factory/engine/tests/workflow/test_workflow.py::test_a_quorum_larger_than_the_task_count_is_refused, but the owner's issue 55 edit does not tick criteria)

**Choices made where this file was silent (2026-11-21, issue 55)**

- Phase 1b `any` and `quorum:N`: the join runs once enough tasks are done, tasks still running are stopped and not joined, and a quorum that cannot be reached fails the stage.
- Hook point keys `add_task`, `add_gate` and `replace_skill`, with the shapes shown above. An added task or gate goes after the stage's own, and `replace_skill` acts on a task because a stage has no skill.
- A plugin manifest's `when` is checked when the run reaches the inserted stage. If it fails, the stage is marked skipped.
- A `changed_paths` glob matches the files the run branch changes from its base, the diff the scope check reads.
- A hook is killed after 10 minutes, the same default as the repo hook timeout in module 17A.
- Hooks and plugin checks run under `srt` with the same rules as a plugin task, because no spec text gives them their own boundary.
- The merged workflow of a plugin is checked with the same goto check as any workflow, so a missing goto target fails the load.
- A plugin's `goto` must name a stage in every workflow its `applies_to` names.
- The license-check example's `applies_to` is narrowed to bug-fix, because only bug-fix has the `fix` stage its `goto` names.

## Decisions

A row changes only through a new `proposed` ADR in `docs/adr/`. To read a folded ADR in full, see `docs/adr/README.md`; the Id cell is the file name without `.md`.

| Rule | Why | Not chosen | Id |
| --- | --- | --- | --- |
| `RunSpec` has `script`, `python` and `args`. Exactly one of `script` and `python` is set. | It freezes what the spec already writes and changes no example. The schema can check it. | A tagged union with a `kind` field. | 2026-11-14-runspec-script-or-python (Q4) |
| Accept the draft report schemas as the phase 1 schemas. | The drafts are the smallest shape that makes bug-fix run. A live run will show whether a field is wrong. | Keep them as drafts until a live run. Also write a merge schema now. | 2026-11-15-accept-draft-report-schemas (wave 3 D1) |
| The bug-fix `verify` to `fix` loop has `max: 3`. | The shipped value is the one the tests pin. A walkthrough example is the easier thing to change. | Keep `max: 2` and change the walkthrough. | 2026-11-15-bug-fix-loop-count-3 (wave 3 D2) |
| Keep phase 2 PRs #39 and #40 on main. `reviewer-eval.yaml` ships in the phase 1 kit. | No work is needed. The owner accepted the cost that `factory init` copies the workflow. | Move the workflow out of the kit. Revert both PRs. | 2026-11-15-keep-reviewer-eval-on-main (wave 3 D3) |
| The reviewer eval is its own workflow, `reviewer-eval`, not a stage in `bug-fix.yaml`. A person starts it by hand. A scheduled or CI run, an eval stage in any shipped workflow, and cases under `factory/` each need a new ADR. | A stage would cost money on every bug fix, grade fixtures not the real change, and put fixtures in the kit. | An eval stage in `bug-fix.yaml`. | 2026-11-15-reviewer-eval-outside-bug-fix |
| Keep the nine choices made where this file was silent: joins, hook keys, `when`, `changed_paths`, timeout, `srt`, goto checks and the license example. | The section marks each choice as made where the file was silent, so a reader can tell it from a rule the file already had. | None recorded: the owner's walkthrough option list is not in the repo (the ADR says so). | 2026-11-21-keep-the-nine-module-5-choices |
| A plugin task exits 0 on pass, 1 on a failed check and 2 on a task error. A result with no `status` is decided by `passed`. | A check that reports `passed: false` must not pass the gate. | None recorded: the owner's walkthrough option list is not in the repo (the ADR says so). | 2026-11-21-plugin-exit-codes-match-the-spec |
| A research question list is plain questions. A `task_template` on the stage builds one task per question. | A plain list is the only form that shows just the questions, and the template keeps task settings in one place. | Full task objects written by the scope step. | 2026-11-21-research-questions-use-a-task-template (D2) |
