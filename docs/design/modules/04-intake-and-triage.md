# 4. Module: intake and triage

Part of the [phase 1 design](../phase-1.md#module-map). Build wave: 2. Contracts and acceptance criteria are in this file; shared types are in [section 18](../shared/18-shared-contracts.md). Terms such as run, stage, task, attempt and rework are defined in the [glossary](../phase-1.md#2-glossary).

Every source is converted into the same `request.json` at pick-up, before the run is created, because the run's name needs the title. A triage stage then picks the workflow by rules, using an LLM only when the rules fail.

| Source | How it arrives | How it is picked up |
| --- | --- | --- |
| CLI | `factory add "title" --type bug --body file.md` | Immediately |
| Markdown | A file dropped in `.factory/inbox/` | `factory sync` or `factory watch` |
| GitHub issue | An open issue with the `factory` label | `factory sync` or `factory watch`, via `gh issue list` |

```json
{
  "schema_version": 1,
  "request_id": "gh-42",
  "source": {"type": "github", "ref": "owner/payments-api#42", "title": "Login fails on expired token",
             "body": "Steps to reproduce...", "labels": ["bug"], "author": "alice", "files": []},
  "body_sha": "c91e07",
  "repo": "payments-api",
  "title": "Login fails on expired token",
  "type": null,
  "type_source": null,
  "priority": "high",
  "acceptance": ["Expired token returns 401 with a refresh hint"]
}
```

A markdown request uses front matter for the same fields:

```markdown
---
title: Login fails on expired token
type: bug
priority: high
acceptance:
  - Expired token returns 401 with a refresh hint
---
Steps to reproduce...
```

Every run starts with the shared `_triage` stage from `factory/workflows/_triage.yaml`. `run.json` has `workflow: null` until triage resolves one; the engine then appends the chosen workflow's stages. The run folder exists from pick-up, but the run worktree and branch are created only when triage ends, because the workflow's `policy.write` decides between a branch and a detached worktree. The `classify` task runs in its task folder with no repo access.

```yaml
# factory/workflows/_triage.yaml
stages:
  - id: triage
    tasks:
      - {id: rules, cmd: [factory, triage], out: triage.json}             # code only
      - {id: classify, skill: classify, needs: [rules], when: {artifact: triage.json, confidence_below: 0.8},
         out: triage.json}                                              # LLM fallback
    gate: [{check: type-resolved}]
    approval: when-low-confidence
```

**Rules**

- Triage order: explicit type, then label, then front matter, then keyword rules. Only if all fail does an LLM task propose a type with a confidence score. A low score becomes a human stop with the candidate workflows as options.
- Duplicates are caught by source ref plus body hash, so the same issue never starts two runs. The check covers active runs, archived runs and `history.jsonl`. When a run ends, the engine removes the `factory` label from its GitHub issue, so a finished issue is not picked up again.
- If a GitHub issue body changes while its run is active, the engine logs `request_changed` and raises an attention item. It does not restart the run by itself.
- Status goes back to the source at each change: GitHub labels `factory:queued`, `factory:running`, `factory:needs-human`, `factory:blocked`, `factory:done`, `factory:failed` plus a comment at the start, at each human stop and at the end; markdown front matter `factory_status` and `factory_run`; for the CLI, printed output and `factory status`.

**Markdown submissions.** Several files submitted together form one run:

- A folder in the inbox, such as `.factory/inbox/new-color/`, is one submission. Its files are combined into one `request.json`, with the `title` taken from the first file's front matter or heading.
- A single loose file is one submission.
- From the CLI, `factory add --files a.md b.md` is one submission.
- `factory watch` picks up a folder only after it has had no new files for 10 seconds, so a half-copied folder is not split.
- Dedupe uses the folder path plus a hash of all its files.

**Module contract: 4 Intake and triage**

- **Depends on:**
  - 3: `load_config`, `validate`
  - 6A: `factory_home`, `repo_key`, `new_run_id`, `init_run`, `find_by_source`, `append_event`
  - 7: `TrackerAdapter`, `snapshot_kit`
- **Writes:** `request.json` and the initial run folder in the factory home, with its `paths` block; events `run_created`, `request_invalid`, `request_duplicate`, `request_changed`.
- **CLI it backs:** `add`, `sync`, and the internal `triage`.

```python
# intake.py
def read_sources(repo: Path, cfg: Config, tracker: TrackerAdapter,
                 kinds: tuple[str, ...] = ("github", "markdown")) -> list[Source]
def normalize(source: Source, cfg: Config) -> Request         # FactoryError("intake.invalid") with reason
def create_run(repo: Path, cfg: Config, request: Request, tracker: TrackerAdapter) -> RunRef
    """dedupe (runs, archive, history) -> run id -> kit snapshot (7) -> state in the factory home (6A), with the worktree path reserved
    but not created (6B creates it when triage ends) -> status back to source."""
def sync(repo: Path, cfg: Config, tracker: TrackerAdapter) -> SyncReport   # created, invalid, duplicates
def add(repo: Path, cfg: Config, title: str, *, type: str | None = None,
        body: str | None = None, files: list[Path] | None = None) -> RunRef
# triage.py
def triage_rules(request: Request, cfg: Config) -> TriageResult
    """type, workflow, confidence, type_source: explicit | label | front_matter | keyword. The rules never return `llm`:
    the classify task writes `type_source: llm`, which the merge policy never auto-merges (module 13)."""
def check_type_resolved(spec: GateSpec, ctx: GateContext) -> GateResult      # used by 8
```

- **Run and test:** `pytest factory/engine/tests/intake` with `FakeTracker` and a temp git repo; `factory sync --json`.
- **Errors:** an invalid request creates no run and its source gets the reason; `gh` errors use transient retry; a duplicate is skipped; an edit mid-run logs `request_changed`.

Acceptance criteria:

- [ ] An inbox folder with three markdown files gives one run; a loose file gives one run; `add --files` gives one run.
- [ ] A folder still receiving files is not picked up until 10 seconds without new files.
- [ ] The same source ref and body hash never creates a second run.
- [ ] A request with no title gets `factory:invalid` and a comment (GitHub) or `factory_error` (markdown), and no run.
- [ ] The run id is a hyphen slug plus 5 characters and never matches an existing branch or run folder.
- [ ] A created run has request.json, run.json with its reserved paths, a run folder in the factory home and the `factory:queued` label; its worktree, shims and branch appear only after triage.
- [ ] `triage_rules` follows the order explicit, label, front matter, keyword, and records `type_source`.
