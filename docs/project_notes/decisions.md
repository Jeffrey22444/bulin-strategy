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

### ADR-003: Indicator Alignment Requires Same Exchange Candle Source (2026-07-01)

**Context:**
- Hyperliquid and most exchange APIs expose OHLCV candles but not chart indicator values such as RSI.
- The active live strategy compares locally computed RSI with thresholds and expects those readings to match the exchange website chart closely.

**Decision:**
- Any RSI value used for live trading must be computed from OHLCV candles fetched from the same exchange environment whose chart is being matched.
- Hyperliquid testnet live trading uses Hyperliquid testnet candles; Hyperliquid mainnet live trading uses Hyperliquid mainnet candles.
- Future exchange integrations must compute RSI from that exchange's own candles before claiming chart alignment.
- RSI formula, method, warmup/history length, and completed-candle handling must be configurable and validated against manually sampled chart readings before live use.

**Alternatives Considered:**
- Use candles from another exchange or cached research data -> Rejected: RSI cannot reliably match the target website chart.
- Use local RSI without chart calibration -> Rejected: prior validation found indicator mismatch risk.

**Consequences:**
- Strategy portability requires per-exchange indicator calibration.
- Backtest or third-party candles are not acceptable as live indicator authority for chart-matching RSI decisions.

### ADR-002: Keep Hyperliquid Live Runner Independent From Backtest Package (2026-06-30)

**Context:**
- The live runner needs trailing setup, confirmation, entry-signal, and feature-building helpers from the trailing strategy.
- Mainline should not import the broad research/backtest package just to run Hyperliquid testnet live execution.

**Decision:**
- Put the live-required trailing helpers in neutral modules: `src/bbmr/trailing.py` and `src/bbmr/trailing_features.py`.
- Keep the Hyperliquid live runner under `src/bbmr/live/` and make it depend on those neutral helpers, not `src/bbmr/backtest/*`.

**Alternatives Considered:**
- Copy `src/bbmr/backtest/` into mainline -> Rejected: brings research architecture into the live integration.
- Keep live imports pointing at backtest helpers -> Rejected: makes backtest package a runtime dependency.

**Consequences:**
- Mainline live execution can use the trailing strategy without merging the full backtest stack.
- Focused tests must protect the shared trailing helper timing behavior.

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
