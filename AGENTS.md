# AGENTS.md

## Read Order

Use progressive disclosure. Read only what is needed for the current task.

1. Read this file first.
2. Read `docs/project_notes/key_facts.md` for stable project facts.
3. Read `docs/project_notes/decisions.md` before planning or changing architecture.
4. Search `docs/project_notes/bugs.md` before debugging familiar errors.
5. Read and update `docs/project_notes/issues.md` when work starts, progresses, blocks, or completes.
6. Read task-specific files only after the relevant memory file points to them or the task requires them.

## Project Memory System

This project keeps institutional knowledge in `docs/project_notes/`.

- `bugs.md`: bug log with causes, fixes, and prevention notes.
- `decisions.md`: architectural decisions and trade-offs.
- `key_facts.md`: non-sensitive project facts, ports, URLs, paths, and conventions.
- `issues.md`: worklog for plans, handoffs, execution progress, blockers, and completion notes.

### Memory Protocol

- Before proposing architecture or workflow changes, check `docs/project_notes/decisions.md`.
- Before debugging an error, search `docs/project_notes/bugs.md` for similar issues.
- Before assuming project configuration, check `docs/project_notes/key_facts.md`.
- Actively update `docs/project_notes/issues.md` with meaningful work progress.
- When resolving a bug, add or update an entry in `docs/project_notes/bugs.md`.
- When making or changing a durable decision, add or update an ADR in `docs/project_notes/decisions.md`.
- Do not store secrets, tokens, passwords, private keys, or credential values in project notes.

## Planning Zone

Planning-zone agents only plan and discuss problems.

- Clarify the goal, constraints, risks, and acceptance criteria.
- Check relevant project memory before proposing a plan.
- Write a handoff for the execution zone when implementation is needed.
- Do not edit production code unless explicitly asked.
- Record planning progress, open questions, and handoff links in `docs/project_notes/issues.md`.

### Handoff Format

Use this structure for execution handoffs:

```markdown
## Goal

## Context

## Files To Read First

## Steps

## Acceptance Criteria

## Stop Conditions
```

## Execution Zone

Execution-zone agents only execute the handoff or task document.

- Read this file, relevant project memory, and the supplied handoff.
- Follow the handoff steps with the smallest working change.
- Do not add extra features, redesigns, broad refactors, or unsolicited suggestions.
- If the handoff is ambiguous, blocked, unsafe, or conflicts with project memory, stop and ask the user.
- Record start, progress, blockers, and completion in `docs/project_notes/issues.md`.

## Editing Rules

- Keep changes small and localized.
- Prefer existing code, standard library, and existing dependencies.
- Do not batch-delete files or directories.
- If deletion is needed, delete only one explicit file path at a time.
- If bulk deletion seems necessary, stop, explain the consequence in beginner-friendly language, and wait for user approval.
- If the same error happens twice, research 3-5 likely fixes, choose the most efficient one, and implement it.
