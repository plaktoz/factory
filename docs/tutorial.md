# Tutorial: your first factory run in a new project

This page takes you from nothing to a merged pull request, in three parts. In part 1 you run one small `chore` on a scratch repo, and the factory opens a pull request that you merge. In part 2 you file a GitHub issue and the factory turns it into a bug fix. In part 3 you add the factory to a project you already have. The dashboard sits between parts 1 and 2.

Every command and output below comes from a real run on 2026-11-21 and 2026-11-22 (macOS, Claude Code through a gateway). Times and run ids differ on your machine.

Both parts need a GitHub repo you can push to. Make an empty private one, such as `you/factory-scratch`, and use it only for this page.

## Before you start

You need:

- `git`, `gh` (logged in: `gh auth status`), Node (for `srt`, the sandbox) and `uv`.
- Python 3.10 or newer.
- Credentials for Claude: `ANTHROPIC_API_KEY`, or `ANTHROPIC_AUTH_TOKEN` with `ANTHROPIC_BASE_URL`. A login session does not work in phase 1.
- The factory source: a checkout of this repo. Set `FACTORY_SRC` to its path, for example `export FACTORY_SRC=~/src/factory`. Every `$FACTORY_SRC` below uses it.

## Part 1. A new project

### 1. Install the `factory` command

```sh
uv venv ~/factory-venv
VIRTUAL_ENV=~/factory-venv uv pip install -e "$FACTORY_SRC/factory/launcher"
export PATH=~/factory-venv/bin:$PATH
```

**`factory` must be on the `PATH`.** The first stage of every workflow runs the command `factory triage` as a task. That task starts with a minimal environment, so if the shell that started the run did not have `factory` on its `PATH`, the `rules` task fails with `factory: command not found` and the run blocks at `triage` (checked 2026-11-21). Put the `export` line in your shell profile.

Check it:

```sh
factory doctor --no-repo
```

Each check should pass. If `credentials` fails, set the variables from "Before you start".

### 2. Make a scratch repo

The scratch repo needs a branch named `main`, one commit, and a script at `scripts/check` that tests your code.

```sh
mkdir scratch && cd scratch
git init -q -b main
mkdir src scripts
printf 'def greet(name):\n    return "hello " + name\n' > src/hello.py
```

The `chore` workflow ends with a `verify` stage that runs `scripts/check`. Two rules for that script, both learned the hard way:

- It must write a file called `check.log` into `$FACTORY_TASK_DIR`. The workflow declares `out: check.log`. A script that exits 0 without writing it counts as failed. When you run the script by hand, `$FACTORY_TASK_DIR` is not set, so the script below writes `check.log` into the current folder instead.
- It must not leave files in the worktree. A check that writes `__pycache__` is discarded.

```sh
cat > scripts/check <<'EOF'
#!/bin/sh
PYTHONDONTWRITEBYTECODE=1 python3 -c 'import sys; sys.path.insert(0, "src"); import hello; assert hello.greet("a") == "hello a"' > "${FACTORY_TASK_DIR:-.}/check.log" 2>&1
EOF
chmod +x scripts/check
git add . && git commit -q -m "add hello"
```

### 3. Install the kit

```sh
factory init
```

```text
4 created, 0 unchanged
```

`init` copies the kit into `factory/` and creates `.factory/config/`. Commit both, because a run reads the kit from the committed `main`:

```sh
git add factory .factory && git commit -q -m "add the factory kit"
```

If you skip the commit, `factory add` stops with `config.invalid: main has no factory/ or .factory/config/ folder`. If your branch is not called `main`, rename it: `git branch -m main`.

Now connect the repo to GitHub, push it, and create the factory's labels there. `init --github` makes the `factory:*` labels that the factory puts on issues:

```sh
git remote add origin https://github.com/you/factory-scratch.git
git push -u origin main
factory init --github
```

Replace `you/factory-scratch` with your repo. `factory doctor` should now show every check passing.

### 4. Add a request

```sh
factory add "Greet with an exclamation mark" --type chore --no-run
```

```text
created run greet-with-an-exclamation-mark-6v61l
```

`--no-run` creates the run and starts nothing. `factory status` lists it.

### 5. Run it

```sh
factory run --all
```

The run goes through three stages:

| Stage | What happens |
| --- | --- |
| `triage` | A deterministic task (`factory triage`) and a classifier check that the request is a `chore`. |
| `implement` | A Claude worker edits the code in its own worktree. Two gates check the diff: `scope-diff` and `lint-clean`. In the real run it changed `src/hello.py` and updated the assertion in `scripts/check`. |
| `verify` | The engine runs `scripts/check` under the sandbox. |

`factory status` shows each stage's state. Run it with `--json` for the stages of each run: the output is one object, and the runs are in `data.runs`. Without `--json` it prints only a count.

The run takes about a minute. It ends at `awaiting_approval`, with a pull request open:

```text
greet-with-an-exclamation-mark-zavus awaiting_approval
hint: factory inbox lists the decisions to answer
```

`factory inbox` names the pull request:

```text
greet-with-an-exclamation-mark-zavus [merge_review] Pull request #4 waits for review: https://github.com/you/factory-scratch/pull/4
```

This stop is the merge policy at work. A `chore` is not in the `auto` list in `.factory/config/merge-policy.yaml`, so a person reviews and merges it. Open the pull request, read the diff (it changes `src/hello.py` and the assertion in `scripts/check`), and merge it on GitHub, or from the terminal:

```sh
gh pr merge 4 --merge
```

The run does not notice the merge by itself. A scheduled `tick` does, and you can run one by hand:

```sh
factory tick
```

```text
started 1, resumed 0
```

`factory status` now shows the run as `done`. To run `tick` for you every few minutes, use `factory schedule install`.

**The pull request body.** Its `What changed` section reads `Not available: the run's worktree could not be read` when your base branch is not the repo's default branch. Your branch from step 2 is the default, so you will see the file list.

### When a run blocks

`factory status` names the stage. Then:

```sh
factory events <run> --json  # what happened, newest last (without --json it prints only a count)
factory where <run>         # the run folder, the worktree and the branch
```

Each task keeps its log in `<run folder>/tasks/<task>/worker.log`. When a gate or a check discards work, the diff is saved next to it as `discarded-<n>.patch`; read that first. Then `factory retry <run>`, `factory goto <run> <stage>`, or `factory abort <run>`.

## The dashboard (between the parts)

```sh
factory dashboard --detach --port 8765
```

It prints a URL with a token, and the server keeps running after the command returns. Open the URL. The page is read-only and plain. From top to bottom it has:

- **Counters.** Running, Needs you, Blocked, Conflict warnings and Done today.
- **Needs you.** Runs that wait for a human, each with the command to run. It says `Nothing waiting.` when there is none. A run at `merge_review` shows here.
- **Runs.** One row per run: repo, title, stage and status. Click a row to see its files and events.
- **Show JSON.** The raw state, from `/api/state.json`. The API needs the `X-Factory-Token` header, which the page sends for you. A request with the token only in the address gets `403`.

The page refreshes every 5 seconds. A warning at the top says `no tick has been recorded yet` until a `tick` runs. If you lose the URL, the token is in `$FACTORY_HOME/dashboard.json`. To stop the server, read its pid from `dashboard.json` (the `pid` field) and run `kill <pid>`. Do not use `pkill -f`: it matches any process whose command line names the server, such as a scan of its source file.

## Part 2. Fix a GitHub issue

In part 2 the request is a GitHub issue and the workflow is `bug-fix`. The same repo works, after you add what `bug-fix` needs.

### What `bug-fix` needs from your repo

The kit's `bug-fix` workflow is an example for one layout. Its `reproduce` stage has the gate `scripts/repro-fails.sh`, and its later stages run `make build`, `make test-api`, `npm --prefix web test` and `make e2e`. Commands that a workflow calls belong to your repo. A repo without `scripts/repro-fails.sh` blocks at `reproduce`:

```text
gate_failed  cmd: [scripts/repro-fails.sh]  gate.exit_code  exit_code: 127
run_blocked  reproduce failed and has no on_fail edge
```

Exit code 127 means the command was not found. Your repo can supply its own `bug-fix` workflow, and the factory looks in `.factory/config/workflows/` before the kit's `workflows/`. This one fits the scratch repo: it reproduces the bug, fixes it, and runs `scripts/check`.

```sh
mkdir -p .factory/config/workflows
cat > .factory/config/workflows/bug-fix.yaml <<'YAML'
name: bug-fix
type: bug
sink: pull_request
policy:
  write: true
  deny_paths: [".github/**"]
defaults:
  retries: 2
  timeout_minutes: 30
  checkpoint_every_minutes: 10
  max_restarts: 3
stages:
  - id: reproduce
    tasks: [{id: repro, skill: reproduce, scope: ["scripts/**", "tests/**"], out: repro.json}]
    gate: [{cmd: [scripts/repro-fails.sh]}]
  - id: fix
    needs: [reproduce]
    tasks: [{id: change, skill: fix, scope: ["src/**"], out: fix.json}]
    gate: [{check: scope-diff}]
  - id: verify
    needs: [fix]
    tasks: [{id: check, cmd: [scripts/check], out: check.log}]
    on_fail: {goto: fix, max: 2}
YAML
```

Two details matter. The `reproduce` task has a `scope` that lets it write a test, because a worker with no scope cannot add a file (in the first attempt, the worker wrote down its analysis and said it could not write a test). The gate script passes only when the reproduction fails, so a failing test must exist before the fix:

```sh
cat > scripts/repro-fails.sh <<'SH'
#!/bin/sh
# Passes only when the reproduction fails.
if PYTHONDONTWRITEBYTECODE=1 python3 -c 'import sys; sys.path.insert(0, "src"); import hello; assert hello.greet("") == "hello, friend!"' >/dev/null 2>&1; then
  echo "the reproduction passes, so the bug is not reproduced" >&2
  exit 1
fi
SH
chmod +x scripts/repro-fails.sh
git add .factory/config/workflows scripts/repro-fails.sh
git commit -q -m "add a bug-fix workflow for this repo"
git pull -q --rebase origin main   # part 1 merged a pull request, so main has moved
git push -q origin HEAD:main
```

Commit and push, because a run reads `.factory/config/` from the committed base branch. A run you create before the commit keeps the old workflow.

The `git add` names the two paths this step creates, so nothing else in the working tree is committed. `git pull --rebase` is needed because part 1's merge is on `main` now, and a push from before it is rejected with `fetch first`. If you use a base branch other than `main`, put its name in both places.

### File the issue and run it

An issue becomes a run when it is open and has the `factory` label. Add `bug` as well, and triage picks `bug-fix`:

```sh
gh issue create --title "greet() returns 'hello !' for an empty name" --label factory --label bug \
  --body "greet('') returns 'hello !'. It should return 'hello, friend!' when the name is empty. Add a check for the empty name."
factory sync
```

`sync` reads every open issue in the repo that has the `factory` label, not only the one you just filed, and creates a run for each one it has not seen. An old issue with that label gets a run too. It starts no engine:

```text
1 new run(s)
```

If it says `0 new run(s)` a moment after you file the issue, run it again: GitHub's issue list can lag by a few seconds. The same issue never makes a second run, so run it only once per issue. Then run the new run:

```sh
factory run greet-returns-hello-for-an-empty-name-lpchj
```

The run goes through `reproduce`, `fix` and `verify`, and stops at the merge review in about a minute and a half. In the real run the `reproduce` task wrote `tests/test_hello.py` with a failing test for the empty name, and the `fix` task changed `src/hello.py`:

```diff
+    if not name:
+        return "hello, friend!"
```

Merge the pull request and run `factory tick`, as in part 1. The run goes to `done`. The pull request body ends with `Closes #<issue>`, and GitHub closes the issue when the pull request merges into the repo's default branch.

### What the issue shows

The factory moves the issue's `factory:*` label as the run moves, and writes a comment at each stop: `factory:queued` when it picks the issue up, `factory:running` while it works, `factory:needs-human` with a comment at a stop (a decision or the merge review), `factory:blocked` with the `factory retry` command, and `factory:done` or `factory:failed` at the end. The change is built and tested against a fake tracker (item 36 in `docs/tasks.md`). It has not run against real GitHub, so check the labels on your first issue. Without it, `factory status` and the dashboard show the same state.

## Part 3. Add the factory to a project you already have

A new project is easy. An existing one has its own test tools, its own lint rules and its own `AGENTS.md`. This part ran on a real project, a Python library with 175 tests, `uv` and `ruff`. Steps 2 to 4 each fix a failure from that run.

**What the project needs first:** a `main` branch (see part 1, step 3 if yours has another name); `ruff` and `pytest` installed in a `.venv` inside the project; tests that pass; and code that `ruff check` and `ruff format --check` accept. The `verify` stage runs both, so a project that fails either one blocks at `verify`, and the log names the file.

Run everything on a copy first. Replace the address with your repo's, and do every step in the copy:

```sh
git clone https://github.com/you/your-project.git factory-try
cd factory-try
```

The kit adds 131 files to the repo. A run makes its own working copy (a *worktree*) under `~/.factory/worktrees/`.

### 1. Install the kit

Do part 1, step 1 (install the `factory` command), then, in the copy, the commands of part 1, step 3 (`factory init`, commit, `factory init --github`). `init` leaves your `AGENTS.md`, your CI and your config alone. It adds `factory/` (the *kit*) and `.factory/config/` only. If you skip this step, nothing below works, and `factory add` says that `main` has no `factory/` folder.

### 2. Keep your linter out of `factory/`

`factory/` holds the kit's own Python, 84 files. If your lint covers the whole repo, it now fails. In the real project, `ruff check .` went from passing to 1,672 errors, almost all `E501` (line too long), once the kit was in. Tell the linter to skip the folder. For `ruff`, add this to `pyproject.toml`:

```toml
[tool.ruff]
extend-exclude = ["factory"]
```

Do the same for your test runner. This project set `testpaths = ["tests"]` in `pyproject.toml`, so `pytest` never looked in `factory/`. If yours collects from the repo root, set `testpaths` (or `norecursedirs`) the same way. The kit's own tests are not copied, but its other Python is.

### 3. Put your tools on the `PATH`

`factory doctor` checks the tools of your language profile (the file `factory/languages/python.yaml`). For Python it runs `ruff` and `pytest` by their bare names. A project that keeps them in its own `.venv` fails the check:

```text
failed: 7 of 8 checks passed
hint: toolchain:python:ruff: install ruff; the python profile needs it
```

Put the venv first on the `PATH` in the shell that starts the factory:

```sh
export PATH="$PWD/.venv/bin:$PATH"
factory doctor
```

```text
8 of 8 checks passed
```

### 4. Write `scripts/check` for a sandbox with no network

Your project's test command is the `chore` workflow's `verify` stage. The stage runs `scripts/check` under a sandbox that writes only to the worktree and the task folder, and that has **no network**. So `uv run pytest`, which syncs and downloads, fails. Two real runs showed it:

```text
error: Could not create temporary file
  cause: Operation not permitted (os error 1) at path "~/.cache/uv/.tmp8mM7RN"
```

```text
error: Failed to download `typing-inspection==0.4.5`
  cause: tunnel error: unsuccessful
```

The engine has no setting that lets a `cmd` task (a task that runs a command, as `verify` does) reach a package index, so the script must use the tools already installed. Call `pytest` and `ruff` directly, point them at your own code folders, and turn their caches off, because a cache is a file in the worktree. The script below names `src tests scripts`; change that list to your project's folders, and leave out any that do not exist:

```sh
mkdir -p scripts
```

```sh
cat > scripts/check <<'EOF'
#!/bin/sh
# The factory's verify step. No network, and writes only to the worktree and $FACTORY_TASK_DIR.
set -e
export PYTHONDONTWRITEBYTECODE=1
{
  pytest -q -p no:cacheprovider
  ruff check --no-cache src tests scripts
  ruff format --no-cache --check src tests scripts
} > "${FACTORY_TASK_DIR:-.}/check.log" 2>&1
EOF
chmod +x scripts/check
```

The two rules from part 1 still hold: the script writes `check.log` into `$FACTORY_TASK_DIR` (the task's own folder, which the sandbox lets it write to) and leaves no file in the worktree. Test it the way the engine runs it, with a minimal environment. This test was run on the real project: exit code 0, 175 tests passed, and `git status --short` showed nothing new.

```sh
mkdir -p /tmp/taskdir
env -i HOME="$HOME" PATH="$PATH" FACTORY_TASK_DIR=/tmp/taskdir ./scripts/check; echo $?
git status --short   # nothing new
```

Commit the script and the `pyproject.toml` change on `main`, because a run reads the committed `main`, then run a request:

```sh
git add scripts/check pyproject.toml && git commit -m "add the factory's verify step"
```

```sh
factory add "Test that a non-empty prompt is refused when the context window is zero" --type chore --no-run
factory run --all
```

```text
created run test-that-a-non-empty-prompt-is-refused-mmk74
```

`factory status --json` showed `triage`, `implement` and `verify` all `done`. The worker added one test to `tests/test_precheck.py` (8 lines, in the project's own style: a `pytest.raises` on `ContextOverflow` and an assert on `model_limit`), and `summary.md` read `Scope check passed · Gates 3 passed, 0 failed`.

### What this part did not check

The last step opens the pull request, and the real run did not get that far. The project's remote was a local folder, so `gh pr create` stopped with `git.auth_expired: ... none of the git remotes configured for this repository point to a known GitHub host`. The first two parts show that step on GitHub. This part did not push to the real project's repository, because it is public and its `AGENTS.md` asks for approval before any push.

## Clean up

```sh
gh repo delete you/factory-scratch --yes   # asks for the delete_repo scope if you lack it
rm -rf scratch
factory abort <run>                        # for any run still open
rm -rf factory-try                         # the copy from part 3
```

