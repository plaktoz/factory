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
      - {check: helpers-ledger}
    on_fail: {goto: root-cause, max: 2}     # rework with a feedback record
    on_conflict: {goto: fix, max: 1}        # merge conflict at join
    approval: none                # none | human | when-low-confidence
    on_reject: {goto: propose}    # where a rework answer sends the run
```

**Rules the engine enforces**

- Tasks with no `needs` start together, up to the concurrency limit. A task with `cmd` and no `skill` runs without an LLM.
- Gates run in order and stop at the first failure. Prefer a command or schema check; use an LLM rubric only inside a task whose output a schema gate then reads.
- `tasks_from` builds a stage's task list from an earlier artifact at run time. The engine validates the generated tasks against the workflow schema before starting them.
- Lookup order: `.factory/config/workflows/`, then `factory/workflows/`. Built-in workflows: bug-fix, feature, new-app, chore, research.
- A workflow file is checked against `factory/schemas/workflow.schema.json`. Only `stages` is required. A file that omits keys gets these values: `name` from the file name, `type` from the name, `policy.write: false`, `sink: pull_request` when it writes and `comment` when it does not, and the `defaults` values in the example above. A task with `cmd` and no `skill` gets `retries: 0` unless it sets its own.
- A stage with `verify` as its id has `sync_base: true` unless the file says otherwise.
- `load_workflow` reports every problem it finds in one `config.invalid` error, each with the file, the line where the YAML has one, and the path inside the file. It also resolves each task's `skill` through module 10. `validate_workflow` takes no repo, so it does not check skill names.
- Two parallel tasks overlap when their scopes can match the same file. A listed file in `shared_files` clears an overlap only when it is the one file the two scopes share. Two glob scopes that overlap are always reported, because one listed file cannot cover every file they match.

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
    on_fail: {goto: fix, max: 2}
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
    approval: human                     # confirm the sub-questions
  - id: gather
    needs: [scope]
    tasks_from: questions.json          # one task per sub-question, in parallel
    task_template: {skill: gather, helpers: {mode: off}, timeout_minutes: 20}
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

- Hook points: insert a stage before or after any stage, add a task or a gate to a stage, replace a stage's skill. Limit any of them with `when` (changed paths, labels, workflow type).
- Plugins apply in file order and never edit workflow files. Each added stage records its source, such as `plugin:frontend-review`, in `run.json`.
- The gate reads only the findings JSON, so free-form skill output never decides pass or fail. Impeccable needs a one-time design context per repo, listed as a plugin setup step; check its license and command names before pinning.

**Deterministic plugin tasks, checks and hooks**

A plugin can add work that runs without any LLM: a command, a script file or a Python function it ships. These run under the same rules as built-in tasks: a timeout, a log, an artifact and a gate. They cost no tokens.

| Kind | In the manifest | How it runs |
| --- | --- | --- |
| Command | `cmd: ["npm", "run", "lint"]` | An argument list, no shell, in the worktree |
| Script | `run: {script: scripts/scan_licenses.py, args: [...]}` | `.py` runs with the engine's Python. An executable file runs directly. `.sh` or `.ps1` only on the systems listed in `os:` |
| Python function | `run: {python: checks.licenses:scan}` | Imported from the plugin folder in a separate Python process |
| Skill | `skill: impeccable-audit` | An LLM worker, as before |

```yaml
# .factory/config/plugins/license-check/plugin.yaml
name: license-check
version: 0.1.0
applies_to: [feature, bug-fix, chore]
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

**Safety**

- `factory plugins enable` lists every command, script and function the plugin will run, then records a hash of the plugin folder in `$FACTORY_HOME/plugin-hashes.json`, keyed by repo key. The hash is never stored in the repo, so a commit cannot approve its own plugin change.
- If any plugin file changes later, the plugin is switched off until enabled again, so reviewed code is the code that runs.
- Plugins run with your user's rights, so enable only plugins you have read.

**Module contract: 5 Workflows and plugins**

- **Depends on:**
  - 3: `load_config`, `validate`
  - 8: `known_checks`
  - 10: `resolve_skill`, used to fail fast on unknown names
- **Writes:** nothing at run time; `plugins enable` records the reviewed hash in `$FACTORY_HOME/plugin-hashes.json`.
- **CLI it backs:** `plugins enable`, `plugins disable`.

```python
# workflow.py
def load_workflow(repo: Path, cfg: Config, name: str) -> Workflow
    """Lookup .factory/config/workflows, then factory/workflows; apply plugins; validate."""
def validate_workflow(wf: Workflow, cfg: Config) -> list[Problem]
    """schema, needs cycles, overlapping parallel write scopes, unknown skill or check,
    unknown goto target, shared_files owners exist."""
def expand_tasks_from(stage: Stage, artifact: Path) -> list[TaskSpec]   # validated like static tasks
    """artifact is a JSON array with one task object per item. Each item must match the workflow schema's task form,
    and the list must pass the checks of a static stage (needs, cycles, overlapping scopes). `task_template` is phase 1b."""
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
                approval: str; on_reject: str | None; sync_base: bool; source: str   # workflow or plugin:<name>
@dataclass
class TaskSpec: id: str; skill: str | None; cmd: list[str] | None; run: RunSpec | None; scope: list[str]; deny: list[str]
                needs: list[str]; helpers: HelperPolicy; out: str | None; timeout_minutes: int
                retries: int; model: str | None; when: dict | None
```

- **Run and test:** `pytest factory/engine/tests/workflow` against the five built-in workflows and broken fixtures; `factory plugins enable frontend-review --json`.
- **Errors:** all fail fast at load or enable; no run starts on an invalid workflow.

Acceptance criteria:

- [x] All built-in workflows and `_triage` load without problems. (test: factory/engine/tests/workflow/test_workflow.py::test_built_in_workflow_loads_without_problems for _triage, bug-fix and chore, the three that ship in phase 1a; the other built-ins are phase 1b)
- [x] A cycle in `needs`, an unknown skill, an unknown check or an unknown `goto` stage are each reported with their path. (test: factory/engine/tests/workflow/test_workflow.py::test_a_needs_cycle_between_stages_is_reported_with_its_path, ::test_a_needs_cycle_between_tasks_is_reported_with_its_stage, ::test_an_unknown_skill_is_reported_with_its_path, ::test_an_unknown_check_is_reported_with_its_path, ::test_an_unknown_goto_is_reported_with_its_path)
- [x] Two tasks that can run together with overlapping write scopes fail unless one `needs` the other or the file is in `shared_files`. (test: factory/engine/tests/workflow/test_workflow.py::test_two_parallel_tasks_with_overlapping_scopes_fail, ::test_a_needs_between_the_tasks_lifts_the_overlap, ::test_a_literal_file_in_shared_files_is_exempt)
- [ ] A plugin inserts its stage at the right place, records `plugin:<name>` as source, and never edits a workflow file. (not ticked: plugins are phase 1b; no plugin loader exists and tests/workflow has no plugin test)
- [x] `expand_helpers` returns sibling tasks for `none` and the task itself for `native`. (test: factory/engine/tests/workflow/test_workflow.py::test_expand_helpers_native_returns_the_task_itself, ::test_expand_helpers_none_returns_one_sibling_per_hint)
- [x] Tasks from `tasks_from` failing the schema stop the stage before any worker starts. (test: factory/engine/tests/workflow/test_workflow.py::test_generated_tasks_that_fail_the_workflow_schema_are_refused (the check is expand_tasks_from, which returns no task on a bad item; no caller in the engine runs a worker yet, as module 6B is not merged))
- [ ] A plugin task with `cmd`, `script` or `python` runs without an LLM, writes its artifact and log, and follows the exit code rules. (not ticked: plugin tasks are phase 1b; no test runs a plugin cmd, script or python task)
- [ ] A plugin whose files changed after `enable` is switched off with a message naming the changed file. (not ticked: plugin enable and file hashing are phase 1b; no test)
- [ ] A `.sh` script on a system not listed in `os:` fails the workflow at load, not mid-run. (not ticked: plugin scripts and the os: key are phase 1b; no test or loader check for .sh scripts)
- [ ] A failing hook is logged and the run carries on unchanged. (not ticked: hooks are phase 1b; no test)
