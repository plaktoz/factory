# Tutorial: your first factory run in a new project

This page takes you from nothing to a finished factory run in a new project. You run one small `chore` on a scratch repo. The run changes some code, checks it, and stops at the pull request step.

It covers the new-project path only. Two parts are not written yet: fixing an issue in an existing project, and the dashboard (its page is still a plain placeholder).

Every command and output below comes from a real run on 2026-11-21 (macOS, Claude Code through a gateway). Times and run ids differ on your machine.

## Before you start

You need:

- `git`, `gh`, Node (for `srt`, the sandbox) and `uv`.
- Python 3.10 or newer.
- Credentials for Claude: `ANTHROPIC_API_KEY`, or `ANTHROPIC_AUTH_TOKEN` with `ANTHROPIC_BASE_URL`. A login session does not work in phase 1.
- The factory source. In this page it is the folder `$FACTORY_SRC`.

## 1. Install the `factory` command

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

## 2. Make a scratch repo

The scratch repo needs a branch named `main`, one commit, and a script at `scripts/check` that tests your code.

```sh
mkdir scratch && cd scratch
git init -q -b main
mkdir src scripts
printf 'def greet(name):\n    return "hello " + name\n' > src/hello.py
```

The `chore` workflow ends with a `verify` stage that runs `scripts/check`. Two rules for that script, both learned the hard way:

- It must write a file called `check.log` into `$FACTORY_TASK_DIR`. The workflow declares `out: check.log`. A script that exits 0 without writing it counts as failed.
- It must not leave files in the worktree. A check that writes `__pycache__` is discarded.

```sh
cat > scripts/check <<'EOF'
#!/bin/sh
PYTHONDONTWRITEBYTECODE=1 python3 -c 'import sys; sys.path.insert(0, "src"); import hello; assert hello.greet("a") == "hello a"' > "$FACTORY_TASK_DIR/check.log" 2>&1
EOF
chmod +x scripts/check
git add . && git commit -q -m "add hello"
```

## 3. Install the kit

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

## 4. Add a request

```sh
factory add "Greet with an exclamation mark" --type chore --no-run
```

```text
created run greet-with-an-exclamation-mark-6v61l
```

`--no-run` creates the run and starts nothing. `factory status` lists it.

## 5. Run it

```sh
factory run --all
```

The run goes through three stages:

| Stage | What happens |
| --- | --- |
| `triage` | A deterministic task (`factory triage`) and a classifier check that the request is a `chore`. |
| `implement` | A Claude worker edits the code in its own worktree. Two gates check the diff: `scope-diff` and `lint-clean`. In the real run it changed `src/hello.py` and updated the assertion in `scripts/check`. |
| `verify` | The engine runs `scripts/check` under the sandbox. |

`factory status` shows each stage's state. After `verify`, this repo has no GitHub remote, so the run stops at the pull request step:

```text
git.command_failed: git push -u: fatal: 'origin' does not appear to be a git repository
```

That is the expected end for a scratch repo. With a GitHub remote, the same step pushes the branch and opens a pull request.

## When a run blocks

`factory status` names the stage. Then:

```sh
factory events <run>        # what happened, newest last
factory where <run>         # the run folder, the worktree and the branch
```

Each task keeps its log in `<run folder>/tasks/<task>/worker.log`. When a gate or a check discards work, the diff is saved next to it as `discarded-<n>.patch`; read that first. Then `factory retry <run>`, `factory goto <run> <stage>`, or `factory abort <run>`.

## The dashboard

```sh
factory dashboard --detach --port 8765
```

It prints a URL with a token. Open it to see the runs. The page is read-only and a plain placeholder for now.

## Not covered yet

- Fixing an issue in an existing project. It needs a real GitHub repo.
- A run that opens a pull request. This page stops one step before it.
