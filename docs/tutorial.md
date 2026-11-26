# Tutorial: your first factory run in a new project

This page takes you from nothing to a merged pull request, in three parts. In part 1 you run one small `chore` on a scratch repo, and the factory opens a pull request that you merge. In part 2 you file a GitHub issue and the factory turns it into a bug fix. In part 3 you add the factory to a project you already have. The dashboard sits between parts 1 and 2.

Every command and output below comes from a real run on 2026-11-21 and 2026-11-22 (macOS, Claude Code through a gateway). Times and run ids differ on your machine.

Parts 1 and 2 need a GitHub repo you can push to. Make an empty private one, such as `you/factory-scratch`, and use it only for this page. Part 3 uses a copy of your own project.

## Before you start

You need:

- `git`, `gh` (logged in: `gh auth status`) and `uv`.
- Node 22.12 or newer, and the sandbox `srt` that runs on it: `npm install -g @anthropic-ai/sandbox-runtime@0.0.83`. `factory doctor` checks both and prints this command when `srt` is missing.
- The Claude Code CLI (`claude`) on your `PATH`. The factory starts it for each worker task. Install it with `npm install -g @anthropic-ai/claude-code`, then check it with `claude --version`. The runs on this page used 2.1.330.
- Python 3.10 or newer.
- Credentials for Claude: `ANTHROPIC_API_KEY`, or `ANTHROPIC_AUTH_TOKEN` with `ANTHROPIC_BASE_URL`. A login session does not work in phase 1.
- The factory source: a checkout of this repo, in any folder you like. Set `FACTORY_SRC` to its path, for example `export FACTORY_SRC=~/Developer/factory`. Every `$FACTORY_SRC` below uses it. It is a name used on this page only, and the factory does not read it. It is **not** `~/.factory`: that is the factory home, a different folder (see the next section).

**Windows.** Phase 1 does not run on native Windows. See [Windows](#windows) before you start.

## Where things live

Four places are involved. Keep them apart.

| What | Default path | Made by | Notes |
| --- | --- | --- | --- |
| The source checkout (`$FACTORY_SRC`) | where you cloned this repo | you | Do not move or delete it. `factory init` copies the kit from its `factory/` folder, because the install in part 1, step 1 is editable. |
| The `factory` command | `~/factory-venv/bin/factory` | step 1 of part 1 | A Python virtual environment that holds the program only, not run state. It is an editable install of `$FACTORY_SRC/factory/launcher`, so it stops working if you move or delete the checkout. The folder name is your choice if its `bin` folder is on the `PATH`. It is separate from your project's own `.venv` in part 3. |
| The factory home | `~/.factory`, or `$FACTORY_HOME` if you set it | the factory, on first use | Run state (`runs/`), kit snapshots (`kits/`), `dashboard.json`, `config.yaml` (machine settings), `history.jsonl` and logs. |
| Worktrees | `~/.factory/worktrees/` | each run | One working copy per run. |
| Your repo | the folder you made or cloned | you | Holds `factory/` (the kit) and `.factory/config/` (your settings). Commit both. |

**There is one factory home per machine, shared by every repo.** Runs from every repo you add are kept side by side under `runs/<repo key>/`. One `factory status`, one dashboard and one `tick` or `schedule` cover all of them, and the clean-up commands at the end act on all of them. What is per repo is the kit and `.factory/config/`.

To keep a trial run apart from your real runs, set `FACTORY_HOME` to a new folder in the shell before the first `factory` command, for example `export FACTORY_HOME=~/factory-home-try`. This is read from the code, and the tutorial runs did not use it. It moves the runs, kits and `dashboard.json`, but not the worktrees: their root stays `~/.factory/worktrees` until you set `worktree_root` in `$FACTORY_HOME/config.yaml`. Run `factory config init` once to create that file.

### The final layout

This is the tree you should have after parts 1 and 2, with the default paths. The factory home part and the worktree part were listed from a real `~/.factory` on 2026-11-24. Run ids, kit hashes and file counts differ on your machine.

```text
~/Developer/factory/               # $FACTORY_SRC: your checkout of this repo (not touched by runs)
~/factory-venv/                    # the `factory` command; bin/ is on your PATH

~/scratch/                         # your repo (any folder); also the git repo you pushed
├── src/hello.py
├── tests/test_hello.py            # part 2: written by the reproduce task, merged by the pull request
├── scripts/
│   ├── check                      # part 1: the verify step
│   └── repro-fails.sh             # part 2: the reproduce gate
├── factory/                       # the kit, copied by `factory init` (131 files). Commit it.
└── .factory/
    ├── .gitignore                 # ignores everything here except config/
    ├── config/                    # your settings. Commit this.
    │   ├── factory.yaml           # base_branch, tracker, harness
    │   ├── merge-policy.yaml
    │   └── workflows/bug-fix.yaml # part 2 (the other folders, plugins/ and overrides/, start empty)
    └── inbox/                     # markdown requests; stays empty and uncommitted here

~/.factory/                        # the factory home ($FACTORY_HOME). One per machine.
├── runs/
│   └── github.com/you/factory-scratch/          # the repo key: host/owner/repo
│       └── greet-with-an-exclamation-mark-zavus/   # one folder per run
│           ├── request.json  run.json  events.jsonl  lock
│           ├── merge.json  summary.md              # appear when the run reaches delivery
│           └── tasks/
│               └── <task>/                         # triage's rules and classify, implement's change, verify's check
│                   └── task.json  worker.log  usage.jsonl  work/
├── worktrees/
│   └── scratch/                                    # your repo's folder name, not the repo key
│       ├── greet-with-an-exclamation-mark-zavus/   # the run's working copy (a full checkout)
│       └── greet-with-an-exclamation-mark-zavus--check/   # a task's own working copy
├── kits/<hash>/                                    # a snapshot of factory/ + .factory/config/ taken when a run is created
├── logs/                                           # engine-<run>.log for each run, tick.log
├── tmp/                                            # scratch folders for workers
├── tick.json  tick.lock                            # written by `factory tick`
└── dashboard.json                                  # written by `factory dashboard`: pid, port, token
```

A repo with no GitHub remote uses `runs/local/<folder>/` instead of `runs/github.com/<owner>/<repo>/`. Some files in the home do not exist until you use them. `config.yaml` (machine settings) appears after `factory config init`, `history.jsonl` and `archive/` after the first cleanup, and `intake/` and `kits/` only once a request or run needs them. The `.factory/inbox/` folder and the empty config folders exist on disk after `factory init`, but git does not commit an empty folder, so a fresh clone does not have them.

The run folder and the worktree folder have the same run id and are different things. The run folder is the factory's record (state, events, logs), and you read it with `factory where <run>` and `factory events`. The worktree is a checkout of your repo where the worker edits files. Nothing in `~/.factory` is part of your repo, and nothing in your repo is part of `~/.factory`, except the kit snapshot under `kits/`, which is a copy.

### When several repos use the factory

Add a second repo the same way as the first: `factory init`, commit the kit, `factory init --github`. The factory home does not change. Each repo gets its own folders under it, and the machine-wide commands see all of them. This section was read from the code (`tick.py`, `cli.py`, `state.py`, `gitops.py`). The tutorial runs used one repo at a time, so none of it was run with two.

**What is shared on the machine**

| Thing | What to expect |
| --- | --- |
| `factory inbox`, the dashboard | Show runs from every repo, one row each, with the repo named. |
| `factory tick`, `factory schedule install` | One tick covers all repos, and only one tick runs at a time: a second tick that starts while one is running exits at once (`tick.lock`). |
| Run ids | Unique across the whole home, so two repos never share a run id. |
| `~/.factory/kits/`, `logs/`, `tmp/` | One folder each for the whole machine. |

**What is per repo**

| Thing | What to expect |
| --- | --- |
| `factory status`, `events`, `where`, `add`, `sync`, `init` | Work on the repo in the current folder, or on `--repo <path>`. `factory status` in repo A does not list repo B's runs. A command that takes a run id (`retry`, `abort`, `where`) finds the run's repo from the id, so it works from any folder. |
| The kit and `.factory/config/` | Each repo has its own, committed in that repo, so the repos can use different workflows, merge policies and kit versions. A run keeps the kit snapshot it was created with. |
| Run folder | `runs/<repo key>/<run id>/`, for example `runs/github.com/you/repo-a/...` and `runs/github.com/you/repo-b/...`. |
| Concurrency | The `concurrency` setting in `.factory/config/factory.yaml` (default 4) limits tasks running at once inside one run. No code limits the total number of runs, or of Claude workers, across repos. |

**Four things that surprise people**

1. **A new repo is not picked up by a scheduled tick until it has a run.** `tick --all-repos`, which `factory schedule install` uses, syncs issues only for repos that already have a run. After `init`, run `factory sync` or `factory add` once in the new repo. After that, the tick finds its labelled issues. The `repos:` list that `factory config init` writes into `config.yaml` is not read by any code, so adding a repo there does nothing.
2. **Worktrees are grouped by the repo's folder name, not its repo key.** Two repos whose folders are both called `app` (`~/work/app` and `~/personal/app`) share `~/.factory/worktrees/app/`. The run ids differ, so the folders do not collide, but you cannot tell the repos apart by that folder. Use `factory where <run>` to see which repo a worktree belongs to.
3. **Two repos with the same remote share one run folder.** The repo key comes from the `origin` URL. Two clones of the same GitHub repo have the same key, so their runs mix under one `runs/<key>/` folder. A repo with no remote uses `runs/local/<folder>/`, so two such repos with the same folder name also mix. Set `repo_key` in `.factory/config/factory.yaml` to give each one its own key.
4. **A deleted or moved repo leaves its runs behind.** The tick reports a run whose repo folder is gone as `repo_missing` and skips it. Abort those runs, or clean up the repo's folder under `runs/`, as in "Clean up".

Which repo a command acts on is the first thing to check when output looks wrong: run it from the repo's folder, or pass `--repo`.

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

`--no-run` creates the run and starts nothing. `factory status --json` lists it (without `--json`, `status` prints only a count).

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

The command prints nothing while the run works. It returns when the run stops. That takes about a minute here, and the run ends at `awaiting_approval` with a pull request open. These two lines are all it prints:

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
gh pr merge <pr-number> --merge   # the number of the pull request the run opened
```

The run does not notice the merge by itself. A scheduled `tick` does, and you can run one by hand:

```sh
factory tick
```

```text
started 1, resumed 0
```

`factory status --json` now shows the run as `done`. To run `tick` for you every few minutes, use `factory schedule install`.

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
- **Needs you.** Runs that wait for a human, each with the command to run. It says `Nothing waiting.` when there is none. A run waiting on its pull request shows here too. Its status is `awaiting_approval`, and its item is of kind `merge_review` (the word `factory inbox` prints in brackets). The two names are for the same stop.
- **Runs.** One row per run: repo, title, stage and status. Click a row to see its files and events.
- **Show JSON.** The raw state, from `/api/state.json`. The API needs the `X-Factory-Token` header, which the page sends for you. A request with the token only in the address gets `403`.

The page refreshes every 5 seconds. A warning at the top says `no tick has been recorded yet` until a `tick` runs. If you lose the URL, the token is in `dashboard.json` under the factory home: `$FACTORY_HOME` if you set it, otherwise `~/.factory`. To stop the server, read its pid from `dashboard.json` (the `pid` field) and run `kill <pid>`. Do not use `pkill -f`: it matches any process whose command line names the server, such as a scan of its source file.

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

`HEAD:main` means "push the commit I am on to the branch `main` on `origin`". It works from any branch, and `main` is where a run reads `.factory/config/`. The `git add` names the two paths this step creates, so nothing else in the working tree is committed. `git pull --rebase` is needed because part 1's merge is on `main` now, and a push from before it is rejected with `fetch first`. If you use a base branch other than `main`, put its name in both places.

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

The message does not print the run id. `factory sync --json` lists it under `data.created`.

If it says `0 new run(s)` a moment after you file the issue, wait a few seconds and run it again: GitHub's issue list can lag. An issue that already has a run is reported under `data.duplicates` and not started again, so `sync` is safe to repeat. Then run the new run, with the id you found:

```sh
factory run <run-id>
```

The run goes through `reproduce`, `fix` and `verify`, and stops at the merge review in about a minute and a half. In the real run the `reproduce` task wrote `tests/test_hello.py` with a failing test for the empty name, and the `fix` task changed `src/hello.py`:

```diff
+    if not name:
+        return "hello, friend!"
```

Merge the pull request and run `factory tick`, as in part 1. The run goes to `done`. The pull request body ends with `Closes #<issue>`, and GitHub closes the issue when the pull request merges into the repo's default branch.

### What the issue shows

The factory moves the issue's `factory:*` label as the run moves, and writes a comment at each stop: `factory:queued` when it picks the issue up, `factory:running` while it works, `factory:needs-human` with a comment at a stop (a decision or the merge review), `factory:blocked` with the `factory retry` command, and `factory:done` or `factory:failed` at the end. This was checked on real GitHub on 2026-11-22 (item 36 in `docs/tasks.md`): an issue went through `queued`, `running`, `needs-human` at the merge review and `done` after the merge, and an issue whose `verify` always failed went to `blocked` with the `factory retry` command in its comment. `factory status` and the dashboard show the same state.

## Part 3. Add the factory to a project you already have

A new project is easy. An existing one has its own test tools, its own lint rules and its own `AGENTS.md`. This part ran on a real project, a Python library with 175 tests, `uv` and `ruff`. Steps 2 to 4 each fix a failure from that run.

**What the project needs first:** a `main` branch (see part 1, step 3 if yours has another name); `ruff` and `pytest` installed in a `.venv` inside the project (`uv sync` does it for a `uv` project, or `python3 -m venv .venv && .venv/bin/pip install pytest ruff`); tests that pass; and code that `ruff check` and `ruff format --check` accept on the folders `scripts/check` names (step 4). The `verify` stage runs both, so a project that fails either one blocks at `verify`, and the log names the file. The credentials from "Before you start" must be set in the shell that runs `factory run`.

Run everything on a copy first. Replace the address with your repo's, and do every step in the copy:

```sh
git clone https://github.com/you/your-project.git factory-try
cd factory-try
```

The kit adds 131 files to the repo. A run makes its own working copy (a *worktree*) under `~/.factory/worktrees/`.

### 1. Install the kit

Do part 1, step 1 (it sets `FACTORY_SRC` and installs the `factory` command), then run the commands of part 1, step 3 in the copy: `factory init`, the commit, and `factory init --github` after you point `origin` at your GitHub repo. `init` leaves your `AGENTS.md`, your CI and your config alone. It adds `factory/` (the *kit*) and `.factory/config/` only. If you skip this step, nothing below works, and `factory add` says that `main` has no `factory/` folder.

### 2. Keep your linter out of `factory/`

`factory/` holds the kit's own Python, 84 files. If your lint covers the whole repo, it now fails. In the real project, `ruff check .` went from passing to 1,672 errors, almost all `E501` (line too long), once the kit was in. Tell the linter to skip the folder. For `ruff`, add this to `pyproject.toml`:

```toml
[tool.ruff]
extend-exclude = ["factory"]
```

Do the same for your test runner. This project set `testpaths = ["tests"]` in `pyproject.toml`, so `pytest` never looked in `factory/`. If yours collects from the repo root, set `testpaths` (or `norecursedirs`) the same way, or `pytest` imports the kit's Python and may fail on it. The kit's own tests are not copied.

### 3. Put your tools on the `PATH`

`factory doctor` checks the tools of your language profile (the file `factory/languages/python.yaml`). For Python it runs `ruff` and `pytest` by their bare names. A project that keeps them in its own `.venv` fails the check:

```text
failed: 7 of 8 checks passed
hint: toolchain:python:ruff: install ruff; the python profile needs it
```

Put the venv first on the `PATH` in the shell that starts the factory, and keep using that shell for the rest of this part:

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

The engine has no setting that lets a task that runs a command (as `verify` does) reach a package index, so the script must use the tools already installed. Call `pytest` and `ruff` directly, point them at your own code folders, and turn their caches off, because a cache is a file in the worktree. The script below names `src tests scripts`; change that list to your project's folders, and leave out any that do not exist:

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

Commit the script and the `pyproject.toml` change on `main` (run `git checkout main` first if you are on another branch), because a run reads the committed `main`, then run a request. Use a small real task from your own project, such as a missing test. The one below is the request that was run on the real project, so replace the words:

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

The real project is public, and its `AGENTS.md` asks for approval before any push, so this part did not push to it. The run used a private copy of the project in its own GitHub repo. The first try of the pull request step failed on a local folder remote, with `git.auth_expired: ... none of the git remotes configured for this repository point to a known GitHub host`. After `origin` pointed at the GitHub copy, `factory run <run>` finished that step without any repair. Pull request #1 opened with one changed file, `tests/test_precheck.py`, and was merged, and `factory tick` ended the run. What was not tried: a repo with branch protection or required CI checks, so the merge-policy side of a pull request is shown only in parts 1 and 2.

## Windows

Phase 1 supports macOS and Linux only. Windows is phase 2 (`docs/design/phase-2.md`, P2-2). The code marks it: `factory schedule install` writes a launchd entry on macOS and a systemd user timer on Linux, and has nothing for Windows. So **do not run this tutorial in PowerShell or `cmd`.** Use WSL2, which gives you a Linux machine inside Windows. No part of this tutorial was run on Windows or WSL2, so treat the steps below as the expected path, not a checked one.

1. In an administrator PowerShell, run `wsl --install -d Ubuntu`, restart, and open the Ubuntu terminal.
2. Do everything in this tutorial **inside** that Ubuntu terminal: install `git`, `gh`, `uv`, Node, `claude` and `srt` there, not on the Windows side. A tool installed on Windows is not on the Linux `PATH`.
3. Keep the checkout, the scratch repo and the copy from part 3 in the Linux home folder (`~/Developer/factory`, `~/scratch`). Do not put them under `/mnt/c/...`. That is the Windows disk seen through a bridge: it is slow, and file modes such as the executable bit on `scripts/check` may not behave.
4. The factory home is then `~/.factory` in Linux, which Windows sees as `\\wsl$\Ubuntu\home\<you>\.factory`. Open the dashboard from a Windows browser at the URL the command prints. WSL2 normally forwards `127.0.0.1` ports to Windows.
5. `factory schedule install` needs systemd running in WSL2. If it is not, run `factory watch` in a terminal you leave open, which does the same job in the foreground.
6. `srt` on Linux needs a few system packages that its own install notes list. `factory doctor` names a missing one. If the check fails, fix it before part 1, step 5.

If you want to run the factory natively on Windows, that needs the phase 2 work: Task Scheduler install, `.bat` and `.ps1` handling, retrying atomic replaces, and `%USERPROFILE%` paths. The file lock already has a Windows branch (`msvcrt`), but nothing else has been tried there.

## Clean up

Do these in order. The run state and the schedule live outside your repo, so deleting the repo does not remove them.

```sh
factory abort <run>                        # for any run still open (factory status --json lists them)
factory schedule remove                    # only if you ran `factory schedule install`
kill <pid>                                 # the dashboard: the pid is in dashboard.json under the factory home
gh auth refresh -h github.com -s delete_repo   # once, if gh lacks the delete_repo scope
gh repo delete you/factory-scratch --yes
rm -rf scratch factory-try                 # the scratch repo and the copy from part 3
```

`factory schedule remove` prints `removed`, or `nothing to remove` when no schedule was installed. Use `kill <pid>`, not `pkill -f factory`, which can stop an unrelated process whose command line contains the word. The finished runs and their worktrees stay under the factory home (`~/.factory` by default); remove a worktree folder only after `git status` in it shows a clean tree. The factory home is shared by every repo on the machine, so do not delete `~/.factory` as a whole unless this tutorial's runs are the only ones in it. If you used a separate `FACTORY_HOME` for the tutorial, that folder is yours to remove, and the worktrees stay in `~/.factory/worktrees` unless you set `worktree_root`. The source checkout (`$FACTORY_SRC`) and `~/factory-venv` are not removed by anything above. Delete `~/factory-venv` once you no longer use the `factory` command, and keep the checkout while any repo still uses it, because the install points at it.

