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

- [ ] A Java-only task gets only the Java pack; a task touching Java and TypeScript gets both.
- [ ] A team override in `.factory/config/overrides/practices/` is used in place of, or merged with, the shipped pack.
- [ ] A pack over `max_lines` is reported by `factory doctor`.

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

- [ ] Resolution order is override, then locked, then own.
- [ ] A skill not in the allowlist is never fetched; denied entries are never installed.
- [ ] Shims appear in a new worktree and never show in `git status`.
- [ ] A changed upstream ref is reported by `verify_lock`.
- [ ] With an empty `skills.lock`, every stage of every built-in workflow resolves to an `own` skill.
- [ ] Each own skill asks no question: run against `FakeWorkerAdapter` fixtures, it writes an artifact that passes its schema or a decision packet.
