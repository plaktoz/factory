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
    network:      {test: [repo.maven.apache.org]}   # hosts a step reaches under srt; none for the others (see below)
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
| Java | `pom.xml`, `build.gradle` | Spotless (google-java-format) | Checkstyle or PMD | Maven: `mvn -q test`, then the surefire `TEST-*.xml` files are merged into one `test.junit.xml` in the task folder; under srt the step reaches Maven Central only, through its `network` key (see the profile format below). Gradle: `gradlew test`, no report yet |
| TypeScript, JavaScript | `package.json` | Prettier | ESLint | `npm test` with jest-junit, which writes `test.junit.xml` into the task folder |
| Python | `pyproject.toml` | `ruff format` | `ruff check` | `pytest --junitxml`, which writes `test.junit.xml` into the task folder |
| Go | `go.mod` | `gofmt` | `golangci-lint` | `go test -json ./...`, converted to `test.junit.xml` in the task folder |
| C# | `*.csproj` | `dotnet format` | `dotnet format --verify-no-changes` | `dotnet test`, no report yet |

These are defaults. A repo whose build lacks a tool (such as the Spotless plugin in `pom.xml`) gets a `factory doctor` warning with the fix. The factory never edits build files outside a run.

**The test step writes a JUnit report (owner correction, 2026-11-25).** The test tool follows the project type: JUnit for a Java project, Jest for a React or TypeScript project, pytest for Python. The engine's `test-report` gate reads JUnit only (`gates.parse_junit`; `Engine._test_report_for_stage` globs `*.junit.xml` in a task's work folder), so a `test` step must leave a `*.junit.xml` file in `$FACTORY_TASK_DIR`. A command runs with no shell, so `$FACTORY_TASK_DIR` is not expanded in an argv. A step that needs the folder is a short `node -e` or `python3 -c` program that reads the variable (the adapter sets it for a `cmd` task), runs the real tool, and exits with the tool's own exit code, so a failed test still leaves its report. Without the variable the program exits 2 and writes nothing. A wrapper's argv starts with an interpreter, so each wrapped profile lists the tool it runs in a `tools` key, and `factory doctor` checks that tool before a run; a tool missing at run time exits 127 with `<tool>: command not found`, which a `cmd` task counts as a check failure (`classify_exit`), not a task error, because the wrapper's own exit code is what the adapter sees. What was run, on 2026-11-25:

| Profile | What the test step does | Run with |
| --- | --- | --- |
| TypeScript (npm) | `node -e` runs `npm test` with `--reporters=jest-junit` and `JEST_JUNIT_OUTPUT_FILE` set | jest 29 and jest-junit 16, through CommandAdapter under srt (PR #197) |
| Python (ruff) | `python3 -c` execs `pytest --junitxml=$FACTORY_TASK_DIR/test.junit.xml` | pytest 9.1.0 on a temp project, through CommandAdapter under srt: a passing run, and a failing run that exits 1 and keeps the file |
| Java (maven) | `python3 -c` runs `mvn -q test`, then merges each `TEST-*.xml` that run wrote under a `surefire-reports` folder into one `test.junit.xml` in the task folder, the file the engine waits for. Surefire's `reportsDirectory` has no `-D` property (the plugin descriptor of 3.2.5 has no user property for it, and `-DreportsDirectory=` changed nothing), so the step reads the reports itself. A report older than the run's start is not merged. A build with no report writes no file | mvn 3.10.0, surefire 3.2.5 and JUnit 5.10.2 on a temp project: a passing run, a failing run that keeps its report, and a build that fails before any test (no report copied). Under srt with `repo.maven.apache.org` allowed (2026-11-25): a passing run on a temp JUnit 5 project, through the shipped step, with no `~/.m2` and the cache under the task folder; the same step with the host denied fails on plugin resolution |
| Go | `python3 -c` runs `go test -json ./...`, echoes the text, and writes one case per test. A package that does not compile is one failed case named for the package | go 1.27.3 on a temp module, through CommandAdapter under srt: passing, failing, and a package that does not compile |

Not verified, so unchanged: **Gradle** (`gradlew test`: gradle is not installed here, so its report folder is not checked; to check, run it on a temp project and look where the JUnit XML lands, then copy it as the Maven step does) and **C#** (`dotnet test`: dotnet is not installed here; a JUnit logger for `dotnet test` is a package in the project under test, which is a new dependency, so the owner should decide before it is added). **Maven under srt (resolved 2026-11-25, owner decision `profile-steps-whitelist-their-registries`):** the adapter points `maven.repo.local` at an empty folder in the task folder, and srt allows no network by default, so `mvn` cannot resolve its plugins from Central. The Java test step's variant names one host under `network`, `repo.maven.apache.org`, and the engine allows that host for that one step. Maven's resolver ignores the JVM proxy properties srt's agent sets, so the step also passes `mvn -s` a settings file with srt's proxy (taken from `HTTPS_PROXY`, written into the task folder at mode 0600). Measured on `srt` 0.0.83 and Maven 3.10.0: with the host allowed the shipped step resolves its plugins and surefire runs the test; with it denied the same step fails with `Could not transfer artifact ... repo.maven.apache.org`. The other steps are verified the same way and none is whitelisted: npm (jest and jest-junit installed beforehand) and pytest pass with no host; Go needs more than a host, because its module download is refused by TLS trust under srt (`x509: OSStatus -26276`), so Go stays unwhitelisted and its test step is untested under srt for downloads.

**The Maven step's failure cases.** Without `HTTPS_PROXY` (outside srt) the step passes no `-s` and writes no file. With `HTTPS_PROXY` set, the step writes the proxy settings file at mode 0600 into the task folder and removes it when `mvn` ends, on success, failure or a missing binary (exit 127); a test checks both the success and the failure path. A `HTTPS_PROXY` with no host or no numeric port exits 2 with `HTTPS_PROXY must be a URL with a host and a port` before `mvn` runs (tested for three malformed values). When srt itself is missing, the command never starts: `sandbox.srt_missing` is raised before the step runs (module 9).

**The `network` key (profile format).** A variant may name the hosts its steps reach under srt: `network: {<step>: [host, ...]}`, where each step is one of `format`, `format_check`, `lint`, `test` or `build`. Each host is a plain lowercase hostname with a dot: no scheme, path, port, wildcard, IP address or empty string. The loader refuses any other value with `config.invalid`, and so refuses a step name it does not know. A step with no key gets no host. A host named for one step is not given to another step or to any other task, and the factory home and the credential folders stay denied (tests: `factory/engine/tests/toolchains/test_step_network.py`).

**Where lint and format run (decided: engine steps, plus repo hooks at join and push)**

1. **When a worker has stopped:** at the end of an attempt, and before a restart that delivers a note, the engine runs `format` on the task's changed files, then makes the final WIP commit. Checkpoints taken while the worker runs commit as they are.
2. **At each code stage's join:** the `lint-clean` gate runs `format_check` and `lint` on changed files. Findings route back for rework, with file, line and rule in the feedback record.
3. **In verify:** `tasks_from: languages` makes one `test` task for each detected language whose files the run changed (a file matches a profile by its `files` globs), run in parallel. A language the run did not touch gets no task (owner decision D5, 2026-11-22). Built (2026-11-25): the engine reads it, and the shipped feature verify stage uses it (owner decision 2026-11-25, `feature-verify-per-language`); the wiring is under "Verify wiring" below the acceptance criteria.
4. **The repo's own git hooks** (pre-commit, husky, lefthook) run on each task commit at join and before push. A failing hook is a gate failure. WIP checkpoint commits skip hooks, so a slow hook never blocks a checkpoint.
5. **For people committing by hand:** `factory hooks install` (optional, off by default) writes a local git hook that runs `factory lint --staged`, so they get the same rules. Nothing is committed to the repo for this.

Every formatter and lint step runs under `srt`, with the same read and write rules as a `cmd` task (module 9), so a formatter cannot write outside the worktree or read the factory home (owner answer, 2026-11-22; a step adds about 0.4 s). The test steps are the exception to this paragraph only in scope: a test step is a `cmd` task when the engine runs it as a verify task, so it runs under srt like any `cmd` task (the wrapper is the argv). The Maven test step runs under srt with its one whitelisted host (see the Maven paragraph above), so no profile step is an exception to the srt rule.

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
- [x] Repo hooks run on the join commit and before push, and a failing hook routes to rework; checkpoint commits skip hooks. (test: factory/engine/tests/engine/test_repo_hooks_route.py::test_a_failing_repo_hook_on_the_join_commit_routes_the_run_back_to_implement, ::test_checkpoints_skip_the_pre_commit_hook_and_only_the_join_runs_it, ::test_a_failing_pre_push_hook_routes_the_run_back_to_rework_and_does_not_crash_the_tick; factory/engine/tests/gitops/test_gitops.py::test_a_failing_pre_push_hook_is_git_hook_failed_with_its_output. The push route is `_push_hook_failed` in engine.py. The join-commit hook's output reaches the feedback record through `JoinResult.hook_output`, section 18, test ::test_a_failing_repo_hook_on_the_join_commit_routes_the_run_back_to_implement)
- [x] A repo with Java and TypeScript gets one verify test task for each language the run changed, run in parallel. (test: factory/engine/tests/engine/test_verify_languages.py::test_a_repo_changed_in_two_languages_gets_one_test_task_for_each_and_the_report_gate_passes, ::test_only_the_language_the_run_changed_gets_a_test_task; factory/engine/tests/toolchains/test_toolchains.py::test_a_java_and_typescript_repo_gets_one_test_task_per_language_with_no_dependencies, ::test_only_the_languages_with_changed_files_get_a_test_task. The shipped feature verify stage uses `tasks_from: languages` (factory/engine/tests/engine/test_verify_languages.py::test_the_shipped_feature_verify_stage_builds_one_test_task_per_changed_language, which runs the shipped feature.yaml on a repo changed in TypeScript and Python). Parallel start of tasks with no `needs` is tested for any task list (engine/test_engine.py::test_tasks_with_no_needs_start_together_up_to_the_concurrency_limit))

**Verify wiring: built (2026-11-25, item 58).** A stage with `tasks_from: languages` builds its tasks as follows. (1) `Engine._specs` takes the run and resolves the `languages` source (`_language_specs`); `tasks_from` still reads a JSON artifact for any other name. (2) The changed files are the run branch's diff against its base (`gitops.changed_files` of the run worktree, base from `gitops.base_ref`), not the implement branches: the implement join deletes each task's branch (`cleanup_after_join`), so those branches are gone when verify starts. (3) The list is decided once, when the stage first starts, and written to `languages.json` in the run folder; later ticks read that file, so a change made between ticks cannot change the stage's tasks. A rework or goto that resets the stage deletes the file, so the next verify decides again (`_reset_tasks`; no test covers this reset yet). If git cannot read the diff, the error is raised before anything is written, so no list is frozen and the next tick tries again. (4) Each task is `toolchains.language_tasks`, with `out: test.junit.xml`, the file its test step writes. A changed file no test task covers is written to a `verify_languages` event with its name, so nothing is skipped silently; a build file (`pom.xml`, `package.json`) counts as covered by the language it configures (`toolchains.uncovered_files`). (5) A run with no test task has 0 test cases, so the T1 block (`gate.no_test_results`) still fires. (6) The Maven test step merges its surefire reports into one `test.junit.xml`, because the engine waits for that name; before, it copied each report under a longer name, so a Java task never finished. A `languages` stage takes no static tasks (refused at load).

Owner decision, 2026-11-25 (`feature-verify-per-language`): the shipped feature verify stage no longer runs `scripts/check`. It is `needs: [implement]`, `tasks_from: languages`, `gate: [{schema: test-report}]`, `on_fail: {goto: implement, max: 2}` (`factory/workflows/feature.yaml`), so a feature run is verified by the per-language test tasks. The owner chose this over keeping `scripts/check` and over running both. The stage list stays four stages. Chore and bug-fix keep `scripts/check`. A repo with no detected profile gets no test task and blocks on `gate.no_test_results` (T1), so a repo whose only check is `scripts/check` needs a profile before its feature runs can pass verify.
- [x] The test step of the TypeScript, Python and Go profiles, and of the Maven profile under srt with its host allowed, leaves a `*.junit.xml` file in the task folder, a failing test run still leaves it and exits non-zero, and the step refuses to run (exit 2, no file) without `FACTORY_TASK_DIR`. (test: factory/engine/tests/workers/test_command_adapter.py::test_the_python_test_argv_writes_a_junit_file_into_the_task_folder_under_srt, ::test_a_failing_python_test_run_exits_one_and_still_leaves_its_report, ::test_the_maven_test_argv_writes_one_merged_junit_file_into_the_task_folder, ::test_a_failing_maven_test_run_exits_nonzero_and_still_leaves_its_report, ::test_a_stale_surefire_report_from_an_earlier_run_is_not_copied, ::test_the_go_test_argv_converts_go_test_json_into_a_junit_file_in_the_task_folder_under_srt, ::test_a_failing_go_test_run_exits_one_and_names_the_failed_test_in_its_report, ::test_a_package_that_does_not_build_is_a_failed_case_not_an_empty_report, ::test_the_python_test_argv_refuses_to_run_without_a_task_folder; TypeScript: ::test_the_typescript_test_argv_writes_its_junit_file_into_the_task_folder_under_srt, which uses a stub `npm`, the real jest run being a hand check in PR #197. The Maven tests run `mvn` directly, not under srt, and need the plugins in `~/.m2`; they skip without them)
- [ ] The test step of the Gradle and C# profiles leaves a `*.junit.xml` file in the task folder. (not ticked: gradle and dotnet are not installed on the build machine, so neither step could be run; the profiles are unchanged)
- [x] `factory doctor` reports a missing tool before any run starts, including the tool a wrapped test step runs. (test: factory/engine/tests/toolchains/test_toolchains.py::test_doctor_reports_a_missing_tool_before_any_run, ::test_doctor_is_silent_about_tools_that_are_present, ::test_doctor_checks_the_test_tool_a_wrapped_test_step_runs_not_only_its_interpreter, ::test_doctor_still_checks_every_other_step_tool_and_the_wrapper_interpreter)

## Decisions

A row changes only through a new `proposed` ADR in `docs/adr/`. To read a folded ADR in full, see `docs/adr/README.md`; the Id cell is the file name without `.md`.

| Rule | Why | Not chosen | Id |
| --- | --- | --- | --- |
| After a skill task's worker stops with an artifact, the engine formats the task's changed files with each matching profile, then makes the final commit. A formatter that exits non-zero fails the attempt as a worker crash and the unformatted files are not committed. A missing formatter is `binary_missing`, a stop for a person. A `cmd` task is not formatted. | Both specs already promised it, and without it each style problem cost a worker round trip through the lint gate. | Leave formatting to the lint gate and the worker's rework (specs reworded, nothing built). | 2026-11-22-owner-calls D8 build-format-step |
| Verify makes a test task only for a language whose files the run changed. | A run that changed Python should not need the Java tools or wait for the Java tests. The owner took the faster option and accepted that a cross-language break can pass verify. | A test task for every language the repo has, whatever changed (safer, slower, and a missing tool for an unrelated language blocks the run). | 2026-11-22-owner-calls D5 changed-only |
| Every formatter and lint step runs under `srt`, like a `cmd` task and a gate command. A formatter that writes outside its worktree is refused. | The factory's rule is that every command it runs goes through the sandbox (module 9), and the formatter runs repo-controlled tool configs. `srt` adds about 0.39 s per call, measured on 2026-11-22 (median of 7; a plain call is 0.006 s). | Keep formatters and lint unsandboxed with a written exception (a second rule, and repo configs run with the engine's HOME). Sandbox only the format step (splits one risk into two rules). | 2026-11-22-formatter-runs-under-srt (owner answer 2026-11-22) |
