# Architectural Decisions

Track durable project decisions here. Use concise ADRs and keep historical context.

## Entry Format

```markdown
### ADR-001: Decision Title (YYYY-MM-DD)

**Context:**
- Why the decision was needed

**Decision:**
- What was chosen

**Alternatives Considered:**
- Option -> Why rejected

**Consequences:**
- Benefits and trade-offs
```

## Decisions

### ADR-001: Use Project Notes for AI Handoffs and Worklog (2026-06-25)

**Context:**
- The project needs continuity across planning-zone and execution-zone AI work.
- Planning should produce handoffs, while execution should follow handoffs without expanding scope.

**Decision:**
- Store project memory in `docs/project_notes/`.
- Use `docs/project_notes/issues.md` as the active worklog for planning progress, handoffs, execution progress, blockers, and completion notes.
- Use `AGENTS.md` as the first-read instruction file for AI agents.

**Alternatives Considered:**
- Keep notes only in chat -> Rejected: hard to reuse across sessions.
- Add a separate automation system -> Rejected: unnecessary for the current need.

**Consequences:**
- Agents have a stable place to read and update project context.
- The process depends on agents consistently following `AGENTS.md`.

