# Key Facts

Store non-sensitive stable project facts here. Put dated, drift-prone observations only in `Last Verified Environment`.

## Stable Project Facts

- Project root: `/Users/jeffrey/Documents/布林带策略`
- AI first-read file: `AGENTS.md`
- Zone rules: `docs/project_notes/zone_operating_model.md`
- Strategy consensus: `docs/strategy_consensus/bbmr_trailing_stop_v1.md`
- Project memory directory: `docs/project_notes/`
- Worklog: `docs/project_notes/issues.md`
- Bug log: `docs/project_notes/bugs.md`
- Durable decisions: `docs/project_notes/decisions.md`
- Focused Python tests use `./.venv/bin/python -m pytest ...`.

## Workflow Zones

- Planning Zone（规划区） discusses goals, constraints, options, and acceptance criteria; it routes an agreed task only after user approval and does not edit production code.
- Execution Zone（执行区） implements the assigned scope, does not invent strategy or design decisions, and records concise execution evidence.
- Acceptance Zone（验收区） is independent and fully read-only; it returns only `通过 / 不通过` plus evidence and never edits code or documentation.
- Maintenance Zone（维护区） inspects Git, environment, dependencies, and runtime hygiene; write operations require explicit scope or approval.
- Only zones with a concrete task should be activated.

## Last Verified Environment

- 2026-07-20: Latest accepted slice is `SAFETY-8`; closed trade history no longer counts as active protective-stop recovery, while every non-closed unprotected/unknown/recovery trade and unresolved stop-replacement intent remains account-blocking. Repository-audit remediation remains closed and active `trend_riding.mode` remains `shadow`.
- 2026-07-20 23:00 CST: Read-only Maintenance verification classified the runtime as state C. The active testnet-order runner started after the accepted SAFETY-8 source modification; advancing snapshots show BTC/ETH/SOL at `no_1h_setup` without the former false recovery block. No restart is required. Process IDs are observational and may drift.

## Security

Never store secrets here.

Do not store:
- Passwords
- API keys
- Auth tokens
- Private keys
- Database passwords
- OAuth client secrets
- Credential JSON contents

Safe to store:
- Public URLs
- Local ports
- Project IDs
- Non-secret environment variable names
- File paths
- Tooling conventions
