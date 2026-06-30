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

### ADR-005: Live State Uses Pending Setup Store Plus Append-Only Journal (2026-06-30)

**Context:**
- Hyperliquid live runner needed restart-safe pending setup/15m confirmation state and future review/stat evidence without moving backtest reporting into live execution.

**Decision:**
- Keep `live_trades` as the open-position management store.
- Add `live_pending_setups` for unexpired setup recovery and `live_trade_events` as an append-only journal written only at state changes.
- Store live PnL provenance explicitly with `pnl_source` values such as `exchange`, `estimated_local`, or `unknown`.

**Alternatives Considered:**
- Reuse backtest report/ledger tables -> Rejected: broader change and mixes research reporting with live exchange reconciliation.
- Persist every poll snapshot -> Rejected: unnecessary volume for the current recovery/stat requirement.

**Consequences:**
- Live runner can recover pending setup state after restart.
- Future realized PnL/stat review has event history without changing strategy behavior.

### ADR-004: Hyperliquid Live Runner Is Testnet-First and Isolated (2026-06-30)

**Context:**
- `bbmr_trailing_stop_v1` needs terminal-only Hyperliquid testnet execution without allowing old `bbmr_v3_2` filters or mainnet behavior to leak into live decisions.

**Decision:**
- Add a separate `src/bbmr/live/` module, separate live YAML, and explicit CLI/config safety gates.
- Keep live strategy decisions on `configs/strategy_bbmr_trailing_stop_v1.yaml`.
- Require both config and CLI approval before placing testnet orders; keep mainnet locked unless both config and CLI explicitly allow it.

**Alternatives Considered:**
- Extend the existing backtest runner -> Rejected: mixes research backtest state/reporting with exchange reconciliation and order safety.
- Reuse old v3.2 decision flow -> Rejected: would risk old filters affecting live trailing-stop decisions.

**Consequences:**
- Live reconciliation, system-owned stops, and manual intervention handling are isolated from research backtests.
- The live runner can be tested with fake exchanges without network calls.

### ADR-003: Shared Portfolio Mode Is Trailing-Strategy Only (2026-06-29)

**Context:**
- Multi-symbol trailing-stop backtests need one account-level equity curve instead of concatenated per-symbol accounts.
- The old `bbmr_v3_2` path still uses its existing independent manual event loop.

**Decision:**
- Keep `--portfolio-mode independent` as the default for compatibility.
- Allow `--portfolio-mode shared` only for `bbmr_trailing_stop_v1`.
- Use a separate trailing portfolio event loop with shared cash, per-symbol state, and one portfolio equity curve.

**Alternatives Considered:**
- Rework the old event-loop merge path -> Rejected: broader change and higher risk to old strategy behavior.

**Consequences:**
- Shared portfolio summary metrics reflect one account.
- Old independent behavior remains available.

### ADR-002: Keep Trailing Stop V1 Isolated From BBMR v3.2 Filters (2026-06-29)

**Context:**
- `bbmr_trailing_stop_v1` has different entry, sizing, and exit timing rules from `bbmr_v3_2`.
- Reusing the old signal, decision engine, or state machine would bring old filters into the new strategy.

**Decision:**
- Route `bbmr_trailing_stop_v1` to separate feature-building and event-loop modules.
- Keep `bbmr_v3_2` on the existing manual event-loop path.

**Alternatives Considered:**
- Add branches inside the old decision engine -> Rejected: higher risk of old filter leakage.

**Consequences:**
- New strategy timing rules can be tested directly.
- Shared code remains limited to neutral loading, indicators, CLI routing, and report writing.

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
