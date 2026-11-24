# 17A. Module: language toolchains, lint and format

Part of the [phase 1 design](../phase-1.md#module-map). Build wave: 1. Contracts and acceptance criteria are in this file; shared types are in [section 18](../shared/18-shared-contracts.md). Terms such as run, stage, task, attempt and rework are defined in the [glossary](../phase-1.md#2-glossary).

Each language in a repo has a toolchain profile: how to detect it, and the deterministic commands to format, lint, test and build it. The engine formats each task's files once, after its worker has stopped, and gates on a clean lint, so joined code is formatted whatever the worker produced, in any supported language. Mid-attempt checkpoints never format, because a formatter would rewrite files the worker is still editing.

```yaml
# factory/languages/java.yaml   (shipped; repo overrides in .factory/config/languages/java.yaml)
name: java
detect: {any_file: [pom.xml, build.gradle, build.gradle.kts]}
files: ["**/*.java"]
practices: own:practices/java
variants:
  maven:
    when: {file: pom.xml}
    format:       [mvn, -q, spotless:apply]
    format_check: [mvn, -q, spotless:check]
    lint:         [mvn, -q, checkstyle:check]
    test:         [mvn, -q, test]
    build:        [mvn, -q, -DskipTests, package]
  gradle:
    when: {any_file: [build.gradle, build.gradle.kts]}
    format:       [gradlew, spotlessApply]       # gradlew or gradlew.bat, chosen per OS
    format_check: [gradlew, spotlessCheck]
    lint:         [gradlew, checkstyleMain]
    test:         [gradlew, test]
    build:        [gradlew, assemble]
```

| Language | Detected by | Format | Lint | Test |
| --- | --- | --- | --- | --- |
| Java | `pom.xml`, `build.gradle` | Spotless (google-java-format) | Checkstyle or PMD | Maven or Gradle test |
| TypeScript, JavaScript | `package.json` | Prettier | ESLint | `npm test` |
| Python | `pyproject.toml` | `ruff format` | `ruff check` | `pytest` |
| Go | `go.mod` | `gofmt` | `golangci-lint` | `go test ./...` |
| C# | `*.csproj` | `dotnet format` | `dotnet format --verify-no-changes` | `dotnet test` |

These are defaults. A repo whose build lacks a tool (such as the Spotless plugin in `pom.xml`) gets a `factory doctor` warning with the fix. The factory never edits build files outside a run.

**Where lint and format run (decided: engine steps, plus repo hooks at join and push)**

1. **When a worker has stopped:** at the end of an attempt, and before a restart that delivers a note, the engine runs `format` on the task's changed files, then makes the final WIP commit. Checkpoints taken while the worker runs commit as they are.
2. **At each code stage's join:** the `lint-clean` gate runs `format_check` and `lint` on changed files. Findings route back for rework, with file, line and rule in the feedback record.
3. **In verify:** `tasks_from: languages` makes one `test` task for each detected language whose files the run changed (a file matches a profile by its `files` globs), run in parallel. A language the run did not touch gets no task (owner decision D5, 2026-11-22).
4. **The repo's own git hooks** (pre-commit, husky, lefthook) run on each task commit at join and before push. A failing hook is a gate failure. WIP checkpoint commits skip hooks, so a slow hook never blocks a checkpoint.
5. **For people committing by hand:** `factory hooks install` (optional, off by default) writes a local git hook that runs `factory lint --staged`, so they get the same rules. Nothing is committed to the repo for this.

Every formatter and lint step runs under `srt`, with the same read and write rules as a `cmd` task (module 9), so a formatter cannot write outside the worktree or read the factory home (owner answer, 2026-11-22; a step adds about 0.4 s).

**Rules for repo hooks**

- **Task branches are never pushed.** Checkpoint commits that skipped hooks stay local. Only the run branch, built from join commits that passed the hooks, is pushed.
- **A hook that edits files** (an auto-formatting pre-commit hook, for example) aborts the commit. The engine stages the hook's changes and retries the commit once; a second failure is rework.
- **Hook timeout.** Not built: no code reads `hook_timeout_minutes` (checked by grep 2026-11-24), so a hook that hangs is not ended by the engine. The planned rule: hooks get `hook_timeout_minutes` (default 10), and a timeout is reported as a hook failure, not a hang.
- **Hook tools are checked early.** `factory doctor` runs the repo's hooks once in dry-run mode where the framework supports it, so a hook needing a tool that isn't installed is found before a run, not at its join.
- **What counts as a failure.** A hook failure is rework: the hook's output goes into the feedback record for the stage that produced the commit. A hook that fails for reasons outside the change (network, missing tool) is reported as an infrastructure error and retried with backoff, then blocked.

In a repo with several languages, each changed file is matched to a profile by its `files` globs, and each profile's commands run for its own files. `mvn`, `gradlew` and `dotnet` format the whole project, so they run once with no file arguments.

**Module contract: 17A Language toolchains**

- **Depends on:** 3: `load_config`.
- **Writes:** nothing itself; its commands change files in the worktree, and 6B commits them.
- **CLI it backs:** `lint [--staged] [--fix]`, `hooks install`, `hooks remove`, toolchain checks in `doctor`.

```python
# toolchains.py
def detect(worktree: Path, cfg: Config) -> list[Toolchain]          # profiles that apply, variant chosen
def run_step(tc: Toolchain, step: Literal["format", "format_check", "lint", "test", "build"],
             worktree: Path, *, files: list[str] | None = None, log: Path) -> StepResult
def check_lint_clean(spec: GateSpec, ctx: GateContext) -> GateResult   # used by 8
def language_tasks(worktree: Path, cfg: Config, step: str, changed: list[str]) -> list[TaskSpec]   # for tasks_from: languages
def format_changed_files(worktree: Path, cfg: Config, changed: list[str], *, log_dir: Path) -> list[StepResult]   # step 1 below
def parse_findings(tc: Toolchain, output: str) -> list[Finding]        # file, line, rule, message
```

- **Run and test:** `pytest factory/engine/tests/toolchains` with fixture repos for each shipped language and stub tools; `factory lint --json`.
- **Errors:** a missing tool or build plugin fails fast before the stage, with a hint. A formatter that exits non-zero is a task error. Lint findings are rework.

Acceptance criteria:

- [x] Maven and Gradle Java, TypeScript, Python and Go fixtures are detected with the right variant. (test: factory/engine/tests/toolchains/test_toolchains.py::test_detection_picks_the_right_profile_and_variant (Maven, Gradle, npm, ruff, go, dotnet), ::test_a_repo_with_java_and_typescript_detects_both)
- [x] After a worker leaves unformatted code, the task's final commit contains formatted code, and a checkpoint taken while the worker runs does not run the formatter. (test: factory/engine/tests/engine/test_format_after_worker.py::test_the_tasks_final_commit_holds_formatted_code_and_notes_stay_out, ::test_a_formatter_that_fails_fails_the_attempt_and_the_unformatted_file_is_not_committed, ::test_a_cmd_task_is_never_formatted_even_when_it_writes_a_python_file; factory/engine/tests/toolchains/test_toolchains.py::test_format_changed_files_runs_each_profile_on_its_own_files_only, ::test_a_build_tool_formatter_runs_once_with_no_file_arguments. The tests use a stub `ruff`; no test formats a Java fixture)
- [x] A lint violation fails `lint-clean`, and the feedback record lists file, line and rule. (test: factory/engine/tests/toolchains/test_toolchains.py::test_a_lint_violation_fails_lint_clean_and_lists_file_line_and_rule, ::test_a_lint_violation_reaches_the_feedback_record_with_file_line_and_rule (stub ruff on PATH; build_feedback writes the record))
- [x] Repo hooks run on the join commit and before push, and a failing hook routes to rework; checkpoint commits skip hooks. (test: factory/engine/tests/engine/test_repo_hooks_route.py::test_a_failing_repo_hook_on_the_join_commit_routes_the_run_back_to_implement, ::test_checkpoints_skip_the_pre_commit_hook_and_only_the_join_runs_it, ::test_a_failing_pre_push_hook_routes_the_run_back_to_rework_and_does_not_crash_the_tick; factory/engine/tests/gitops/test_gitops.py::test_a_failing_pre_push_hook_is_git_hook_failed_with_its_output. The push route is `_push_hook_failed` in engine.py. Left for the owner: the join-commit hook's output does not reach the feedback record, because `JoinResult` (section 18) has no hook-output field; the feedback holds a fixed sentence)
- [ ] A repo with Java and TypeScript gets one verify test task for each language the run changed, run in parallel. (not ticked: toolchains/test_toolchains.py::test_a_java_and_typescript_repo_gets_one_test_task_per_language_with_no_dependencies and ::test_only_the_languages_with_changed_files_get_a_test_task check `language_tasks`, which nothing in `factory_engine` calls: the shipped verify stages list their `cmd` tasks by hand (bug-fix.yaml, chore.yaml). So no run builds a per-language task list from the changed files, and the parallel start is not tested for that list. Parallel start of tasks with no `needs` is tested for any task list (engine/test_engine.py::test_tasks_with_no_needs_start_together_up_to_the_concurrency_limit))
- [x] `factory doctor` reports a missing tool before any run starts. (test: factory/engine/tests/toolchains/test_toolchains.py::test_doctor_reports_a_missing_tool_before_any_run, ::test_doctor_is_silent_about_tools_that_are_present)

## Decisions

A row changes only through a new `proposed` ADR in `docs/adr/`. To read a folded ADR in full, see `docs/adr/README.md`; the Id cell is the file name without `.md`.

| Rule | Why | Not chosen | Id |
| --- | --- | --- | --- |
| After a skill task's worker stops with an artifact, the engine formats the task's changed files with each matching profile, then makes the final commit. A formatter that exits non-zero fails the attempt as a worker crash and the unformatted files are not committed. A missing formatter is `binary_missing`, a stop for a person. A `cmd` task is not formatted. | Both specs already promised it, and without it each style problem cost a worker round trip through the lint gate. | Leave formatting to the lint gate and the worker's rework (specs reworded, nothing built). | 2026-11-22-owner-calls D8 build-format-step |
| Verify makes a test task only for a language whose files the run changed. | A run that changed Python should not need the Java tools or wait for the Java tests. The owner took the faster option and accepted that a cross-language break can pass verify. | A test task for every language the repo has, whatever changed (safer, slower, and a missing tool for an unrelated language blocks the run). | 2026-11-22-owner-calls D5 changed-only |
| Every formatter and lint step runs under `srt`, like a `cmd` task and a gate command. A formatter that writes outside its worktree is refused. | The factory's rule is that every command it runs goes through the sandbox (module 9), and the formatter runs repo-controlled tool configs. `srt` adds about 0.39 s per call, measured on 2026-11-22 (median of 7; a plain call is 0.006 s). | Keep formatters and lint unsandboxed with a written exception (a second rule, and repo configs run with the engine's HOME). Sandbox only the format step (splits one risk into two rules). | 2026-11-22-formatter-runs-under-srt (owner answer 2026-11-22) |
