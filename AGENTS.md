# AGENTS.md

## Read Order

Use progressive disclosure. Read only what is needed for the current task.

1. Read this file first.
2. Read `docs/project_notes/zone_operating_model.md` to confirm your zone responsibilities, boundaries, output format, and cross-zone handoff rules.
3. Read `docs/project_notes/key_facts.md` for stable project facts.
4. Read only `docs/project_notes/issues.md` Current Summary plus the latest entry relevant to the current task.
5. Read `docs/project_notes/current_task.md` only when the active task or Acceptance Contract has explicitly been parked there.
6. Read `docs/strategy_consensus/bbmr_trailing_stop_v1.md` before discussing or changing the active trading strategy, Hyperliquid live behavior, entry/exit timing, trailing stops, sizing, or manual position handling.
7. Read `docs/project_notes/decisions.md` before proposing workflow or architecture changes.
8. Search `docs/project_notes/bugs.md` before debugging a familiar or recurring error.
9. Read task-specific files only when the task or the relevant project-memory entry requires them.

Items 1-4 are the default startup read set. Everything else is trigger-based; do not read the full project-note set or all of `issues.md` by default.

## Project Memory System

This project keeps institutional knowledge in `docs/project_notes/`.

- `bugs.md`: bug log with causes, fixes, and prevention notes.
- `decisions.md`: architectural decisions and trade-offs.
- `key_facts.md`: non-sensitive project facts, ports, URLs, paths, and conventions.
- `issues.md`: worklog for plans, handoffs, execution progress, blockers, and completion notes.
- `zone_operating_model.md`: responsibilities, boundaries, output preferences, and interaction rules for Planning/Execution/Acceptance/Maintenance zones.
- Optional `current_task.md`: the active complex task or Acceptance Contract only; overwrite it for the next active task instead of using it as history.

### Memory Protocol

- Before proposing architecture or workflow changes, check `docs/project_notes/decisions.md`.
- Before debugging an error, search `docs/project_notes/bugs.md` for similar issues.
- Before assuming project configuration, check `docs/project_notes/key_facts.md`.
- Planning and Execution update `docs/project_notes/issues.md` with meaningful progress and completion evidence.
- Acceptance is fully read-only. After it returns a verdict, Planning or Execution records that verdict verbatim in `issues.md`; Acceptance never edits code or documentation.
- When resolving a bug, add or update an entry in `docs/project_notes/bugs.md`.
- When making or changing a durable decision, add or update an ADR in `docs/project_notes/decisions.md`.
- Do not store secrets, tokens, passwords, private keys, or credential values in project notes.

## Zone Defaults

- Planning Zone discusses goals, constraints, risks, options, and acceptance criteria before creating execution material.
- Execution Zone implements only clearly assigned work, uses the smallest working change, and runs relevant tests.
- Acceptance Zone independently reviews only, gives `通过 / 不通过`, and does not modify code or documentation.
- Maintenance Zone handles Git, environment, dependencies, run state, and mainline cleanliness.
- Activate only zones that have a concrete task. Planning routes work to Execution only after user agreement; Execution must not invent unresolved strategy or design decisions.

## Zone Operating Model

The four-zone workflow is documented in `docs/project_notes/zone_operating_model.md`.

All Planning Zone（规划区）, Execution Zone（执行区）, Acceptance Zone（验收区）, and Maintenance Zone（维护区） agents must read that document before work.

## Strategy Consensus

The active trading-strategy consensus is documented in `docs/strategy_consensus/bbmr_trailing_stop_v1.md`.

All zones should treat that document as the first shared reference for:

- `bbmr_trailing_stop_v1`
- Hyperliquid testnet live behavior
- 1h setup, 15m RSI confirmation, and 5m entry timing
- initial stop and trailing-stop rules
- position sizing
- manual position adopt/add/close handling
- live persistence and journal expectations

If a strategy detail is unclear or appears inconsistent with code/tests, stop and clarify with the user or planning zone before proceeding.

## Editing Rules

- Keep changes small and localized.
- Prefer existing code, standard library, and existing dependencies.
- Do not batch-delete files or directories.
- If deletion is needed, delete only one explicit file path at a time.
- If bulk deletion seems necessary, stop, explain the consequence in beginner-friendly language, and wait for user approval.
- If the same error happens twice, research 3-5 likely fixes, choose the most efficient one, and implement it.
