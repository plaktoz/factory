# Vision

Where the project ends up, and which way to lean when no rule settles a choice. It names no phase: `docs/design/phase-1.md` and `phase-2.md` are the route, and this file is the destination. It changes only through a `proposed` ADR that the owner accepts (section 9).

`AGENTS.md` says how to work. The specs in `docs/design/` say what to build. `docs/process.md` says how this repo is built. This file says what it is for.

## How to use this file

- Read it after `AGENTS.md`, before you choose between options that no rule settles.
- A specific rule beats this file. The order is: the owner's words in this session, then a `Decisions` row or a standing approval in `approvals.md`, then `AGENTS.md`, then this file, then your own judgment. If a rule seems to go against this file, follow the rule and propose an ADR. Do not quietly pick the vision.
- When you log a choice in `decisions.md` or write an ADR, name the principle (P1 to P7) that decided it, so a reader can check the choice against this file.

## 1. The end state

A fully autonomous agentic tool, **autonomous within the owner's policy**. The owner sets direction and policy once: which repos, what may merge, and what stays the owner's to decide. The factory takes the work, plans it, builds it, verifies it, merges it where the policy allows, and reports. The owner is asked only for what the policy marks as theirs.

What stays the owner's is whatever the stop triggers in `AGENTS.md` name: a choice that reopens a recorded decision, changes scope, costs a lot to reverse (a public post under the owner's name, a shared data format, a new dependency), or has no clearly better option. Everything else the factory decides, logs and reports.

The scarce resource is the owner's attention. Tokens, machine time and agent sessions are cheap next to it. A design that saves an hour of compute but adds a question for the owner is usually worse.

Autonomy is granted, not assumed. It widens where a record of passing checks supports it, and it narrows again where a run goes wrong. It is not "zero human": the factory does not write its own policy or pick its own goals.

## 2. What it works on

Any kind of work a person could delegate. Software is the first kind, and the only one with checks built today.

A kind of work is granted autonomy only when it has checks that can tell right from wrong without a person (P2): a test suite and a build for code, and for another kind, whatever plays that part. Where no such check exists, the work goes to a person at that step. Widening to a new kind means writing its checks first.

## 3. Who it serves

| Who | What they need from the factory |
| --- | --- |
| The owner, as operator | Set policy, submit requests, answer only real stops, review what the policy keeps for review. Continue on any machine from the repo alone. |
| Another operator | Install the kit for their own repos and run their own copy, from `docs/tutorial.md` alone. One operator for each install. |
| A target repo | Gets the `factory/` kit, the skill shims and a `.factory/` folder, and nothing else. Its own CI, hooks and rules still apply. |
| LLM workers | Not users. They are the workforce: given a brief, a scope and a gate. |

A hosted service that many people share is not a goal (section 6).

## 4. What success looks like

The owner's time goes into policy and real stops, and the work still gets done. Runs can be killed and resumed at any point without losing work. A change is good if it moves one of these signals the right way and none the wrong way. Most come from `scripts/task-record.py report` and the docs checks.

| Signal | Better when |
| --- | --- |
| Time a run or task waits on the owner | Lower |
| Share of decisions taken at the recommendation | Stays high (71 of 89 answers, 80%, in `docs/process.md`, 2026-11-23); a drop means the recommendations got worse |
| Runs that finish without a person repairing state by hand | Higher |
| Rework loops per run | Lower |
| Spec and code out of step (`records`, `links`, `criteria`, `contracts`) | Zero failures |
| Acceptance criteria ticked with evidence on the line | All of them |

## 5. Principles, ranked

When two principles pull apart, the higher one wins. Most choices touch only one or two.

**P1. Safe and recoverable.** Never lose committed work, never leak a secret, never write outside the scope a task was given. A crash, a sleep or a kill leaves a state the engine can resume from. A workflow must pass with helpers off before native helpers are allowed on.
*So:* take the lock before you remove anything; fail closed when a plugin or gate cannot be checked; keep the worker sandbox on.
*Not:* a faster path that can leave a half-written state file.

**P2. The engine decides.** If code can decide it, code decides it. Only the engine starts tasks, moves stages and merges. Every LLM output passes a deterministic gate before anything depends on it, and the same inputs give the same run. Autonomy rests on trusting those checks, not on trusting a model's judgment.
*So:* rules before a model in triage; a schema gate on every report.
*Not:* asking a worker to judge something a check could settle; a model that plans and drives the run.

**P3. The owner's attention is the budget.** Ask only on a stop trigger. Make each answer cheap: one page, at most five cards, a recommended option, and a command to apply it. Where fewer questions and a fuller record pull apart, fewer questions win: sessions write the records, and the owner's reading time is what cannot be bought.
*So:* decide by default and log it; turn a finding a check can settle into a fix.
*Not:* status updates that end a turn; pages of questions that all have a clear best answer.

**P4. Durable and readable records.** State is files. Every human stop is a file, so it can be answered from the dashboard, the CLI, a chat or an editor. A fresh session on another machine can continue from the repo alone. A fact lives in one file. Text is written for a person to read.
*So:* JSON for state, JSON Lines for logs, YAML for what people write, plain markdown for specs; evidence on the same line as a tick.
*Not:* knowledge that lives only in a session, a chat or one machine; the same fact in two files.

**P5. Product before process.** A working factory comes before better rules for building it. Process earns its place with a measured problem.
*So:* a new skill, check or process ADR waits until the owner asks, or a retro shows the cost it removes.
*Not:* scoring rounds while acceptance criteria are open.

**P6. Light and portable.** The kit is small, replaceable in one step and free of references to this repo. Nothing ties it to one OS, LLM or harness beyond what the work built so far allows.
*So:* the adapter contract stays harness-neutral; an update replaces `factory/` and the shims only.
*Not:* a dependency or a path that only works on the owner's machine.

**P7. Speed and cost.** Faster runs and fewer tokens are good, and they come last. Cost is tracked per attempt, not capped.
*So:* parallel tasks inside a stage; `pytest -n` where it helps.
*Not:* skipping a gate or a check to save time.

## 6. Not goals

- Not an unchecked agent. Autonomy comes from policy and from a record of passing checks. Work the merge policy does not allow to auto-merge waits for a person.
- Not an agent framework or a harness. Claude Code and Codex are workers the engine starts. The engine, not a model, runs the work (P2).
- Not a hosted service shared by many people. One operator for each install; the dashboard listens only on its own machine.
- Not a replacement for a target repo's CI, hooks or own rules.
- Not a spend limiter yet. Budget caps are on hold (`docs/design/modules/14-token-tracking.md`).

A request that needs one of these is a scope change, so it is a stop trigger.

## 7. How to decide

1. **Is it already decided?** Search the `Decisions` tables, `decisions.md` and `approvals.md`. If it is, follow it.
2. **Is it a stop trigger?** (See `AGENTS.md`.) If yes, write a `proposed` ADR, put it on the next page and keep working on what it does not block.
3. **Otherwise, rank the options** by the highest principle each one helps or hurts. Take the best.
4. **Tie?** Take the option that is cheaper to undo. Still tied: fewer files changed, no new dependency, less for a person to read.
5. **Record it at its cost** and name the principle.

Questions to ask of any option:

- Can code decide this instead of a model? (P2)
- Does this add something the owner must read or answer? Can it be avoided? (P3)
- Could a fresh session on another machine continue from what I wrote? (P4)
- Is this fact already stated somewhere else? (P4)
- Does it put a reference to this repo into `factory/`? (P6)
- What is my evidence: a test, a measure, a primary source? Or am I guessing? If guessing, say so.

## 8. Signs a choice has gone wrong

Each one has happened in this repo, and each became a rule.

| Sign | What it cost | Rule that answers it |
| --- | --- | --- |
| Every branch edits one long file | 15 of 86 merges conflicted in `tasks.md` (`AGENTS.md`) | The merger writes `tasks.md` |
| A turn ends on a status update | An estimated 10 hours of owner gaps over 66 sessions, read by keyword (`docs/process.md`) | End a turn only for the owner |
| Decision pages of eight cards | Two batch days hold 64 of 99 answers (`docs/process.md`) | At most five cards a page |
| Process work while product items wait | Calibration runs 3 to 8 in `references/calibration-2026-11-21.md`; the one `ready` was not an independent score (`docs/tasks.md` item 45) | Product before process |
| A tick with no evidence | A reader cannot check it | Evidence on the same line |

If your change looks like one of these, stop and choose again.

## 9. Worked examples

- **`gc` takes the run lock before removing a worktree.** Simpler code could skip the lock. P1 wins over P7: a live run must never lose its worktree (decision `gc-takes-the-run-lock-before-removing-a-worktree`).
- **Pull requests run the four docs checks, not the full engine suite.** The full suite would have stopped PR #170, but it needs `srt`, Chrome and Claude, which a hosted runner lacks, and its speed there is unmeasured. P1 is served by fast checks plus local runs; P3 and P7 rule out a check that cannot run (`docs/process.md`, 2026-11-24).
- **The merger writes `tasks.md`.** A single writer keeps the resume page in one place (P4) and ends the merge conflicts the owner had to sort out (P3).

## 10. Open questions for the owner

1. How autonomy is earned in general. Today the merge policy widens it one workflow at a time, and a chore typed by the triage model does not auto-merge while the same chore typed explicitly does. Whether a clean-run record should widen a repo's policy by itself, and after how many runs, is not decided.
2. What checks a non-software kind of work needs before it earns autonomy (section 2). `docs/design/phase-2.md` P2-10 holds the open questions, and a new ADR comes before any of it is built.
3. Whether a second operator sharing one install is ever in scope. Today the answer is no (section 3).

## 11. Changing this file

Write a `proposed` ADR that names the section and the new text. When the owner accepts it, the same commit edits this file and deletes the ADR. Do not edit this file in any other way.
