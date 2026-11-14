# Appendix A. Operator walkthrough

Part of the [phase 1 design](../phase-1.md#shared-sections).

This is the sequence from a clean machine to a merged fix, using a repo called `report` and GitHub issue #42. Steps 1 to 4 are done once per machine, steps 5 to 7 once per repo, and steps 8 to 15 every time.

**Once per machine**

1. **Prerequisites.** Python 3.10+, `git`, `gh` (for GitHub requests), and the `claude` CLI. Log it in, or prepare its API key.
2. **Install the factory CLI.** Install it once with `pipx install factory-cli`. This launcher finds the kit in each repo's `factory/` folder and runs that repo's engine version, so repos upgrade independently. It also carries the dashboard, since one dashboard serves every repo.
3. **Machine config.** Run `factory config init`, which creates `~/.factory/config.yaml` and an env file. Then fill in:
   - `harnesses` (command paths, models, `${...}` keys)
   - `worktree_root: /home/me/dev/worktree`
   - `tick.every_minutes`
   - the keys in the env file, readable only by you
4. **Check.** Run `factory doctor --as-scheduler`. It must pass before scheduling, because cron starts with an empty environment.

**Once per repo**

5. **Add the kit.** In `/work/report`, run `factory init --github`. It:
   - copies the kit into `factory/`
   - writes `.factory/config/` (`factory.yaml`, `merge-policy.yaml`) and `.factory/.gitignore`
   - creates the GitHub labels (`factory`, `factory:queued`, `factory:needs-human`, and the rest)
   - adds the repo to `repos` in the machine config
6. **Review the settings** in `.factory/config/`: base branch, routing, merge policy, workflows, plugins.
7. **Commit.** Commit `factory/` and `.factory/config/` through a normal pull request. Nothing else from the factory is ever committed.

**Start the services** (once per machine, after the first repo)

8. **Dashboard.** Run `factory dashboard --detach`, then open http://127.0.0.1:8765. `factory schedule install --dashboard` starts it at login.
9. **Scheduler.** Run `factory tick --all-repos` once by hand and check its output, then run `factory schedule install --every 10m`. The dashboard now shows "last tick".

**Every request**

10. **Submit.** Use one of these:
    - label issue #42 `factory` plus a type label such as `bug`
    - drop a folder of markdown files into `.factory/inbox/`
    - run `factory add "Login fails on expired token" --type bug` in the repo
11. **Pick-up.** Within one interval, a tick creates run `login-fails-on-expired-k3m9x`:
    - a branch of that name
    - a worktree at `/home/me/dev/worktree/report/login-fails-on-expired-k3m9x`
    - state at `~/.factory/runs/github.com/acme/report/login-fails-on-expired-k3m9x/`
    - the label `factory:queued` and a comment on the issue

    The run appears on the dashboard at the next refresh. A CLI request skips the wait and starts at once.
12. **Watch.** The dashboard shows stages, tasks, the log tail and token use. To steer a task, add a note on the dashboard, or run `factory note <run>/<task> "..."`.
13. **Answer human stops.**
    - **Where you see it:** the issue gets `factory:needs-human` and a comment, and the run appears under Needs you.
    - **How you answer:** open the decision page, choose, then either copy the command it shows (`factory decide login-fails-on-expired-k3m9x --packet 661cb74d D1=approve`) or press Submit on the dashboard.
    - **Where to run the command:** from any folder, because each run's folder in the factory home records its repo. `factory where <run>` shows every folder of a run.
    - **What happens next:** the engine resumes at once.
14. **Failures.** A failed gate routes the run back automatically, and you see the loop on the stage strip. Only a blocked run needs you; answer its decision page with retry, goto, skip or abort.
15. **Delivery and cleanup.**
    - **Pull request:** opened with `summary.md` as its body and `Closes #42`.
    - **Merge:** a small chore with an explicit type auto-merges. Anything else waits for your review on GitHub.
    - **After merge:** the run is done, the issue is closed and labelled `factory:done`, and the worktree and branches are removed. A worktree that is not clean is removed only when the repo's `cleanup_check` passes; otherwise `factory gc` reports it and leaves it.
    - **Later:** `factory gc` archives the run folder after the retention period.

Useful checks at any time: `factory status`, `factory inbox`, `factory usage`.
