# 10. Module: skills

Part of the [phase 1 design](../phase-1.md#module-map). Build wave: 1. Contracts and acceptance criteria are in this file; shared types are in [section 18](../shared/18-shared-contracts.md). Terms such as run, stage, task, attempt and rework are defined in the [glossary](../phase-1.md#2-glossary).

Each stage resolves to one skill in a fixed order: a local override in `.factory/config/overrides/`, then the locked upstream skill, then the factory's own fallback in `factory/skills/own/`.

```yaml
# factory/stages.map.yaml   (additions go in .factory/config/overrides/stages.map.yaml)
classify:          {skill: own:classify}
reproduce:         {skill: own:reproduce}
root-cause:        {skill: own:root-cause}
propose:           {skill: own:propose}
architect:         {skill: own:architect}
implement:         {skill: own:implement}
fix:               {skill: own:fix}
review-standards:  {skill: own:review-standards}
review-spec:       {skill: own:review-spec}
scope:             {skill: own:scope}
gather:            {skill: own:gather}
synthesize:        {skill: own:synthesize}
critique:          {skill: own:critique}
```

The factory ships its own skill for every stage. Upstream skills such as `diagnosing-bugs`, `tdd`, `code-review`, `grill-me` and `research` are reference material for writing them, not dependencies: the installed versions are interactive (they ask a person questions, start their own subagents or write into the repo), so a gate cannot rely on their output.

**The implement skill says the worker cannot run commands.** The implement worker has no shell (`bash=[]`), so it cannot run the tests or the build. The skill says so, and says that the verify stage runs them after the worker finishes.

**The headless rule.** An own skill never asks a person a question. Where a human is needed, the skill writes a decision packet and the engine raises the human stop. A skill reads its inputs from the prompt, writes one artifact to `$FACTORY_TASK_DIR` that matches the task's output schema, and starts no subagents except as the helper policy allows.

```yaml
# factory/skills.lock   (ships empty; used only by plugins and overrides that name an upstream skill)
sources: {}
allow: {}
deny: {}
# example entry:
#   sources: {example: {repo: owner/skills, ref: <pinned-commit>}}
#   allow:   {example: [skill-name]}
```

- An upstream skill enters only through `skills.lock` with a pinned ref and an allowlist, for a plugin or a local override. Check each license yourself; this is not legal advice.
- The parts that decide pass or fail (verify, ledger check, scope check, critique, the architecture packet schema) are the factory's own, so upstream changes never move a gate.
- Each source is installed by one method only, so no skill exists twice.

**Programming practice packs**

Good practices for each language live in small skill folders, given to a worker only when its task touches that language. They cost context only when they matter.

```text
factory/skills/own/practices/
  java/
    SKILL.md         short core rules: design, errors, naming intent
    testing.md       read only when tests are in scope
    review.md        the checklist for review stages
    spring.md        read only when Spring is detected
  typescript/  python/  go/  csharp/
.factory/config/overrides/practices/java/   the team's own rules, merged over the shipped ones
```

How they stay small:

1. **Tools first.** Any rule a formatter or linter can check lives in the linter configuration (17A), not in prose. Packs hold only what tools cannot check, such as design, error handling and testing approach.
2. **Chosen by code.** 17A's `detect` and the task's scope decide which packs apply. A task scoped to `services/api/**` in a Java repo gets the Java pack; a frontend-only task never sees it.
3. **Pointers, not text.** The prompt lists each pack's path and one-line description. The worker opens `SKILL.md`, and the topic files it points to, only when needed, the same progressive loading skills already use in Claude Code.
4. **A size limit.** Each `SKILL.md` has a line limit (`practices.max_lines`, default 150), and `factory doctor` reports packs over it.
5. **Fit to the stage.** Review stages get `review.md`; fix and implement stages get the core rules.

```python
# skills.py (addition)
def practice_packs(languages: list[str], stage: str, repo: Path, cfg: Config) -> list[SkillRef]
```

- [ ] A Java-only task gets only the Java pack; a task touching Java and TypeScript gets both. (not ticked: practice_packs is tested with a language list the test passes in, but no production code calls it, so no task ever gets a pack from its files)
- [x] A team override in `.factory/config/overrides/practices/` is used in place of, or merged with, the shipped pack. (test: factory/engine/tests/skills/test_skills.py::test_a_team_override_replaces_the_shipped_pack, ::test_a_team_override_can_be_merged_over_the_shipped_pack)
- [ ] A pack over `max_lines` is reported by `factory doctor`. (not ticked: oversized_packs is tested (test_a_pack_over_max_lines_is_reported_and_the_limit_is_configurable) but no code calls it, so factory doctor never reports a pack over its limit)

**Module contract: 10 Skills**

- **Depends on:** 3: `load_config`.
- **Writes:** fetched skills in a machine cache, and shims inside each worktree as `factory-<skill>` folders, hidden by patterns in the repo's shared `.git/info/exclude`.
- **CLI it backs:** `upgrade` (shims), `doctor` (lock check).

```python
# skills.py
def resolve_skill(name: str, repo: Path, cfg: Config) -> SkillRef
    """override -> locked upstream -> own fallback. FactoryError("skills.unknown") if none."""
def install_locked(repo: Path, cfg: Config) -> LockReport        # fetch pinned refs, apply allow and deny
def verify_lock(repo: Path) -> list[Problem]                     # refs present, hashes match
# shims.py
def generate_shims(worktree: Path, harnesses: list[str], skills: list[SkillRef]) -> list[Path]
    """.claude/skills/factory-* links (phase 2 adds .agents/skills for Codex); ensures the exclude patterns exist once per repo."""

@dataclass
class SkillRef: name: str; source: Literal["override", "locked", "own"]; path: Path; args: dict
```

- **Run and test:** `pytest factory/engine/tests/skills` against a local fixture repo standing in for upstream.
- **Errors:** a missing locked skill or an invalid override falls back to `own` with a warning event. With no fallback, it fails fast at workflow load.

Acceptance criteria:

- [x] Resolution order is override, then locked, then own. (test: factory/engine/tests/skills/test_skills.py::test_resolution_order_is_override_then_locked_then_own)
- [x] A skill not in the allowlist is never fetched; denied entries are never installed. (test: factory/engine/tests/skills/test_skills.py::test_a_denied_locked_skill_is_not_used, ::test_only_allowed_skills_are_fetched_and_denied_ones_are_never_installed)
- [x] Shims appear in a new worktree and never show in `git status`. (test: factory/engine/tests/skills/test_skills.py::test_shims_appear_in_a_new_worktree_and_never_show_in_git_status, ::test_shims_in_a_second_worktree_are_also_hidden)
- [x] A changed upstream ref is reported by `verify_lock`. (test: factory/engine/tests/skills/test_skills.py::test_a_changed_upstream_ref_is_reported_by_verify_lock)
- [x] With an empty `skills.lock`, every stage of every built-in workflow resolves to an `own` skill. (test: factory/engine/tests/skills/test_skills.py::test_with_an_empty_lock_every_stage_resolves_to_an_own_skill; its stage list is hand-written and covers every skill name the shipped workflows use: classify, fix, implement, propose, reproduce, review-spec, review-standards, root-cause)
- [ ] Each own skill asks no question: run against `FakeWorkerAdapter` fixtures, it writes an artifact that passes its schema or a decision packet. (not ticked: tests/workers/test_own_skills_against_fake.py proves wiring only (its docstring says so): it scripts each skill's artifact instead of running the skill, so no test shows a skill writes its own artifact on the fake)

## Decisions

A row changes only through a new `proposed` ADR in `docs/adr/`. To read a folded ADR in full, see `docs/adr/README.md`; the Id cell is the file name without `.md`.

| Rule | Why | Not chosen | Id |
| --- | --- | --- | --- |
| The factory writes its own headless skill for every stage. Upstream skills are reference only. | The owner chose this on 2026-11-14. The answer is the record's. No other reason is recorded. | Not recorded in the ADR. | 2026-11-14-factory-writes-its-own-stage-skills (D9) |
| The implement skill tells the worker it cannot run commands, and that the verify stage runs the tests. | The worker has no shell (`bash=[]`), so the old instruction to run the tests could not be followed. The ADR file is empty; this row is built from commit `ac3c9f5` and `docs/tasks-archive.md`. | `let-worker-run-tests` (give the worker a way to run tests): not built, and it needs its own ADR. | 2026-11-21-tell-the-worker-not-to-run-the-tests (owner decision D3, `fix-the-words`, 2026-11-21) |
