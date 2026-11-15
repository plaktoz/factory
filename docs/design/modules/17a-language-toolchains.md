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
3. **In verify:** `tasks_from: languages` makes one `test` task per detected language, run in parallel.
4. **The repo's own git hooks** (pre-commit, husky, lefthook) run on each task commit at join and before push. A failing hook is a gate failure. WIP checkpoint commits skip hooks, so a slow hook never blocks a checkpoint.
5. **For people committing by hand:** `factory hooks install` (optional, off by default) writes a local git hook that runs `factory lint --staged`, so they get the same rules. Nothing is committed to the repo for this.

**Rules for repo hooks**

- **Task branches are never pushed.** Checkpoint commits that skipped hooks stay local. Only the run branch, built from join commits that passed the hooks, is pushed.
- **A hook that edits files** (an auto-formatting pre-commit hook, for example) aborts the commit. The engine stages the hook's changes and retries the commit once; a second failure is rework.
- **Hook timeout.** Hooks get `hook_timeout_minutes` (default 10). A pre-push hook that runs the whole test suite can be slow, and a timeout is reported as a hook failure, not a hang.
- **Hook tools are checked early.** `factory doctor` runs the repo's hooks once in dry-run mode where the framework supports it, so a hook needing a tool that isn't installed is found before a run, not at its join.
- **What counts as a failure.** A hook failure is rework: the hook's output goes into the feedback record for the stage that produced the commit. A hook that fails for reasons outside the change (network, missing tool) is reported as an infrastructure error and retried with backoff, then blocked.

In a repo with several languages, each changed file is matched to a profile by its `files` globs, and each profile's commands run for its own files.

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
def language_tasks(worktree: Path, cfg: Config, step: str) -> list[TaskSpec]   # for tasks_from: languages
def parse_findings(tc: Toolchain, output: str) -> list[Finding]        # file, line, rule, message
```

- **Run and test:** `pytest factory/engine/tests/toolchains` with fixture repos for each shipped language and stub tools; `factory lint --json`.
- **Errors:** a missing tool or build plugin fails fast before the stage, with a hint. A formatter that exits non-zero is a task error. Lint findings are rework.

Acceptance criteria:

- [x] Maven and Gradle Java, TypeScript, Python and Go fixtures are detected with the right variant. (test: factory/engine/tests/toolchains/test_toolchains.py::test_detection_picks_the_right_profile_and_variant (Maven, Gradle, npm, ruff, go, dotnet), ::test_a_repo_with_java_and_typescript_detects_both)
- [ ] After a worker leaves unformatted Java, the task's final commit contains formatted code; a checkpoint taken while the worker runs does not run the formatter. (not ticked: the formatter step (run_step) is called only by tests, and no engine code formats after a worker stops; checkpoint_format is a source grep, not a run; no test formats a Java fixture)
- [x] A lint violation fails `lint-clean`, and the feedback record lists file, line and rule. (test: factory/engine/tests/toolchains/test_toolchains.py::test_a_lint_violation_fails_lint_clean_and_lists_file_line_and_rule, ::test_a_lint_violation_reaches_the_feedback_record_with_file_line_and_rule (stub ruff on PATH; build_feedback writes the record))
- [ ] Repo hooks run on the join commit and before push, and a failing hook routes to rework; checkpoint commits skip hooks. (not ticked: no test runs a repo hook on a join commit or before push; hook behavior is module 7 and the routing to rework is module 6B)
- [ ] A repo with Java and TypeScript gets one verify test task per language, run in parallel. (not ticked: test_a_java_and_typescript_repo_gets_one_test_task_per_language_with_no_dependencies checks language_tasks, which no engine code calls (the verify stage that would use it is module 6B); the parallel run is not tested)
- [x] `factory doctor` reports a missing tool before any run starts. (test: factory/engine/tests/toolchains/test_toolchains.py::test_doctor_reports_a_missing_tool_before_any_run, ::test_doctor_is_silent_about_tools_that_are_present)
