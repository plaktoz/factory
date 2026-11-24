# 15. Module: dashboard

Part of the [phase 1 design](../phase-1.md#module-map). Build wave: 3. Contracts and acceptance criteria are in this file; shared types are in [section 18](../shared/18-shared-contracts.md). Terms such as run, stage, task, attempt and rework are defined in the [glossary](../phase-1.md#2-glossary).

One local Python server, started with `factory dashboard`, serves the dashboard page: a plain HTML page in phase 1a, the prebuilt React bundle in phase 1b (owner decision, 2026-11-15). It reads every run's files in the factory home directly and refreshes every 5 seconds. Its writes go through the same engine functions the CLI uses.

**How the dashboard finds runs**

All run state is in the factory home, so the dashboard needs no registration and no call from the engine. It watches one folder: `$FACTORY_HOME/runs/<repo key>/<run id>/`.

1. Every 5 seconds the server lists the `run.json` files under `runs/`. It remembers each file's modification time and size, and re-reads with 6A `read_run` only files that changed, so a refresh stays cheap with hundreds of runs. It does not call `RunScanner.scan()`: that parses every `run.json` through `list_runs` on each call, and one unreadable file fails the whole scan. A file that cannot be read shows as an unreadable row.
2. A new run folder appears on the next refresh, and a folder archived by housekeeping disappears. There is nothing to register or clean up.
3. Each run shows its repo key and the paths from `run.json` (repo, worktree, task worktrees, branch, source), each with a Copy button. The server never reads repos or worktrees.
4. A run whose repo is gone shows as "repo missing": still readable, but it can't be resumed, and housekeeping archives it.
5. Scheduler health comes from `tick.json` in the factory home.

An OS file watcher could replace polling later, but polling stays the default because it behaves the same on every OS.

**Views**

- **Overview:** counters (running, Needs you, blocked, conflict warnings, done today) and runs grouped by repo.
- **Needs you:** every attention item across repos, oldest first. A decision item has Open page and Copy path buttons; a blocked run has its action buttons.
- **Run detail:** the stage strip with rework loops, tasks with status and attempts, log tail, notes, failure panel, decisions, usage, merge result and conflict signals.
- **Decision page:** the generated HTML file, served as is ([module 11](11-human-stops.md)).
- **Usage:** token totals by observed model, repo and day.
- **Show JSON:** the exact document the page is rendering.

**API**

| Method and path | Does |
| --- | --- |
| `GET /api/state.json` | Every run in the factory home, with attention items, conflict signals and the last tick |
| `GET /api/runs/<id>` | One run: request, run, paths, tasks, decisions, merge result, summary |
| `GET /api/runs/<id>/tasks/<task>/log` | Last 200 lines of `worker.log` |
| `GET /runs/<id>/decisions/<stage>.<n>.html` | The decision page, with a content security policy header |
| `POST /api/runs/<id>/decide` | Records an answer with its packet hash through the launcher, which starts an engine if none holds the lock |
| `POST /api/runs/<id>/note` | Queues a note |
| `POST /api/runs/<id>/retry`, `goto`, `skip`, `abort` | Blocked-run actions |

**Rules**

- The server binds to localhost and rejects any request whose `Host` is not the configured dashboard address, and any `POST` whose `Origin` is not the dashboard itself, so a web page in your browser cannot send commands to it.
- **Session token.** At start the server makes a random token, stores it with its pid and port in `$FACTORY_HOME/dashboard.json` (mode 0600; workers run as the same user, so the factory-home deny-read rule in [module 9](09-worker-adapters-and-governed-helpers.md) is what keeps them out, and the residual risk there applies), and `factory dashboard` prints and opens `http://127.0.0.1:8765/?token=...`. The page keeps the token in memory and sends it on every API call; the server refuses any `/api` or decision-page request without it. A new token is made at each start, so an old bookmark stops working.
- A decision page served by the dashboard gets the token injected when it is served, never saved in the file on disk. Opened from disk, the page still shows the command and cannot submit.
- It has no user accounts. Do not expose it beyond your machine without an authenticating proxy.
- It reads only these files under `$FACTORY_HOME/runs/`: `request.json`, `run.json`, `task.json`, `events.jsonl`, `usage.jsonl`, `decisions/*.yaml`, `decisions/*.html`, `merge.json`, `summary.md` and `worker.log`. JSON and YAML are validated against their schemas and rejected if invalid. Every reader of `events.jsonl`, the dashboard included, skips or ignores `run_snapshot` events; only the rebuild in module 6 reads them.
- It never reads repos or worktrees.
- A run is stale when `lock_status` reports stale, the same rule the tick uses. A heartbeat older than 2 minutes on a live lock shows as "not responding", for display only.
- Finished runs older than `show_finished_days` (default 7) are hidden from the overview until housekeeping archives them.
- In phase 1 the server and all repos are on one machine.
- The browser tab title shows the Needs you count, and an optional browser notification fires when it rises while the page is open.

The wireframe below shows the overview layout. Visual design comes later.

*Overview layout (wireframe, text form)*

| Repo | Task | Stage | Status | Updated |
| --- | --- | --- | --- | --- |
| payments-api | Expired token login bug | fix | running | now |
| payments-api | Refund endpoint | architecture | awaiting approval | 3 min |
| web-portal | SSO options research | gather | running | now |
| infra-tools | Patch report | build | stale | 95 min |

Counters above the table: Running, Needs you, Blocked, Conflict warnings, Done today. Buttons: Show JSON. The page reads the same JSON that Show JSON displays (`GET /api/state.json`); runs are found by `RunScanner` under `$FACTORY_HOME/runs/`.

**Module contract: 15 Dashboard**

- **Depends on:**
  - 6A: `factory_home`, `RunScanner`, `find_run`, `read_run`, `read_events`, `lock_status`
  - 11: the decision page files
  - 12: `tail_log`
  - 14: `summarize`
  - 16: the launcher, called as `factory <command> --json` for every write
- **Writes:** nothing; every change goes through the launcher.
- **CLI it backs:** `dashboard [--port 8765] [--detach]`.

The server is part of the machine launcher, not a repo's kit. It reads files directly, accepting schema major versions N and N-1, so repos on older kits still show. For writes it calls the launcher, so each repo's own engine version applies the change, and it returns the CLI's JSON result to the page.

| Endpoint | Calls | Returns |
| --- | --- | --- |
| `GET /api/state.json` | The server's run index: a listing of `run.json` files, then `read_run` for changed runs (not `RunScanner.scan`, see "How the dashboard finds runs") | All runs, attention items, signals, last tick |
| `GET /api/runs/<id>` | `find_run`, `read_run`, decision files, `merge.json`, `summary.md` | One run, with its paths |
| `GET /api/runs/<id>/tasks/<task>/log` | `tail_log` | Text |
| `GET /runs/<id>/decisions/<stage>.<n>.html` | The file | The page, with a content security policy header |
| `POST /api/runs/<id>/decide` | `factory decide <id> --packet ... --json` | CLI JSON |
| `POST /api/runs/<id>/note` | `factory note <id>/<task> ... --json` | CLI JSON |
| `POST /api/runs/<id>/retry` (`goto`, `skip`, `abort`) | `factory retry <id> --json` and so on | CLI JSON |

- **Run and test:** API tests `pytest factory/launcher/tests/server` against fixture run folders; UI tests against the same fixtures, run as `factory/launcher/tests/server/test_page_ui.py`: headless Chrome loads the real `factory/dashboard/index.html` with a stub `fetch` and clipboard (no Playwright, so no new dependency), and the tests skip when Chrome is absent; `factory dashboard --port 8765`.
- **Errors:** a missing or invalid file shows as an unreadable row. Bad API input gets HTTP 400 with the reason. A port already in use fails fast. A failed CLI call returns its JSON error to the page. A state request that does not answer within 10 seconds is given up: the warning shows "Cannot reach the dashboard (no answer within 10 s, or the connection failed)", and the rows already on screen stay (owner decision, 2026-11-24). The page does not blank the rows.

Acceptance criteria:

- [x] Runs from two repos with different kit versions show on one page. (test: factory/launcher/tests/server/test_api_state.py::test_runs_from_two_repos_on_different_kits_show_on_one_page)
- [x] A new run appears within one refresh with no API call; an archived run disappears. (test: factory/launcher/tests/server/test_page_ui.py::test_a_new_run_appears_on_the_next_refresh_and_an_archived_run_disappears)
- [x] With 500 runs, a refresh re-reads only the run files that changed. (test: factory/launcher/tests/server/test_api_state.py::test_with_500_runs_a_refresh_rereads_only_changed_files)
- [x] A run whose repo was deleted shows as repo missing and can still be opened. (test: factory/launcher/tests/server/test_api_state.py::test_a_run_whose_repo_was_deleted_shows_as_repo_missing_and_opens)
- [x] Run detail shows repo, worktree, task worktrees, branch and source paths, each copyable. (test: factory/launcher/tests/server/test_page_ui.py::test_run_detail_copy_buttons_copy_each_path)
- [x] Needs you lists every attention item across repos, with Open page and Copy path for decisions. (test: factory/launcher/tests/server/test_page_ui.py::test_needs_you_lists_every_item_with_open_page_and_copy_path)
- [ ] (1b) Submit on a decision page records the answer through the launcher and the run resumes. In 1a the page shows the command only. (not ticked: 1b behavior; the launcher call is tested with a fake, and the run resuming needs module 16 and the real engine)
- [x] The page refreshes every 5 seconds without a manual click; Show JSON displays the document in use. (test: factory/launcher/tests/server/test_page_ui.py::test_the_page_polls_the_state_every_five_seconds_without_a_click, ::test_show_json_displays_the_document_in_use)
- [x] Run detail shows token totals by observed model, repo and day, and says so when none are recorded. (test: factory/launcher/tests/server/test_pages_and_writes.py::test_run_detail_returns_token_totals_by_model_repo_and_day, ::test_a_run_with_no_attempts_has_empty_usage_groups, ::test_the_page_renders_each_usage_group_and_the_empty_state; the page's rendering was also driven once in a headless browser against a real server, not as a repeatable UI test)
- [x] A request with no token, a wrong token, a foreign `Host` or a foreign `Origin` is refused with HTTP 403 and changes nothing. (test: factory/launcher/tests/server/test_security.py::test_no_token_wrong_token_foreign_host_or_foreign_origin_is_403_and_changes_nothing)
- [x] Scheduler health shows the last tick from `tick.json`, and warns after `stale_after_ticks` intervals without one. (test: factory/launcher/tests/server/test_api_state.py::test_scheduler_health_shows_the_last_tick_and_warns_when_it_is_stale)

## Decisions

A row changes only through a new `proposed` ADR in `docs/adr/`. To read a folded ADR in full, see `docs/adr/README.md`; the Id cell is the file name without `.md`.

| Rule | Why | Not chosen | Id |
| --- | --- | --- | --- |
| Dashboard writes need a per-session token, a `Host` check and an `Origin` check. | The owner's reason is not recorded. | No other option is recorded. | `2026-11-14-dashboard-writes-need-token-host-and-origin` (D5) |
| Phase 1a ships the plain HTML page with a usage view. The React bundle moves to phase 1b. | The pilot is read-only and the engine path matters more. React can follow in 1b without redoing the server. | `build-react-now` (no React source exists); `plain-page-for-good` (drop React from the spec). | `2026-11-15-dashboard-plain-page-in-phase-1a` (D2, owner decision 2026-11-15) |
