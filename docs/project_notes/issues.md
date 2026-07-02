# Worklog

Track planning, handoffs, execution progress, blockers, and completed work here.

## Entry Format

```markdown
### YYYY-MM-DD - Brief Title
- **Status**: Planned / In Progress / Blocked / Completed
- **Zone**: Planning / Execution / General
- **Description**: 1-2 line summary
- **Handoff**: Link or path, if applicable
- **Notes**: Important context
```

## Entries

### 2026-07-02 - Acceptance Intake For Live Runner Network Error Fix
- **Status**: In Progress
- **Zone**: Acceptance
- **Description**: Accepted the maintenance handoff for the live runner DNS/connection crash and will review execution against the approved minimal fix scope instead of repeating diagnosis.
- **Handoff**: `/private/tmp/bbmr_acceptance_handoff_20260702_network_error.md`
- **Notes**: Acceptance focus is limited to whether `src/bbmr/live/run.py` keeps transient DNS/connection failures recoverable without swallowing unknown or non-network exceptions, and whether `tests/live/test_live_run.py` covers the new `ccxt.base.errors.NetworkError` path.

### 2026-07-02 - Diagnose Live Runner DNS Resolution Crash
- **Status**: Completed
- **Zone**: Maintenance
- **Description**: Inspected a live-run crash where the runner printed one timeout line and then still exited on a Hyperliquid testnet DNS resolution failure.
- **Handoff**: None
- **Notes**: Root cause is in `src/bbmr/live/run.py`: `_is_poll_timeout()` currently treats only read-timeout style exceptions as recoverable, but this crash path is `socket.gaierror -> urllib3 NameResolutionError -> requests.ConnectionError -> ccxt.base.errors.NetworkError`, so the exception is re-raised and the process exits. Existing tests cover `TimeoutError` during balance/positions fetch, but there is no coverage for DNS/name-resolution or generic recoverable network-connectivity failures.

### 2026-07-02 - Keep Live Runner Alive On DNS/Connection Failure
- **Status**: Completed
- **Zone**: Execution
- **Description**: Treating short Hyperliquid testnet DNS/connection failures during poll reads as recoverable network errors.
- **Handoff**: None
- **Notes**: Expanded the live poll recoverable read phase to include ccxt `NetworkError` and requests connection failures, changed the log line to `live poll network error; waiting for next cycle`, and kept unknown exceptions re-raised. Verified with `.venv/bin/python -m pytest tests/live/test_live_run.py -q`.

### 2026-07-01 - Run Live System No-Code Stress Tests
- **Status**: Completed
- **Zone**: Maintenance
- **Description**: Executed no-code stress tests against the live trading runtime for long-run polling stability, restart recovery, state isolation, repeated entry/archive cycles, and timeout resilience.
- **Handoff**: None
- **Notes**: Used temporary SQLite state plus fake exchange/client harnesses that call real `LiveRuntime` and `_poll_once()` code paths without modifying production code. Verified: 3000 idle polling cycles produced zero trades/setups/events and no SQLite growth; 150 repeated restarts preserved exactly one BTC pending setup without event duplication; 1000 managed-position cycles kept one BTC trade with one stop update only and no ETH/SOL contamination; 1000 timeout-injected cycles produced 220 recoverable timeouts without state pollution; 100 repeated setup->confirm->entry->archive rounds closed cleanly with no leaked pending setup or open trade.

### 2026-07-01 - Keep Live Runner Alive On Read Timeout
- **Status**: Completed
- **Zone**: Execution
- **Description**: Catching transient exchange read timeouts at the live loop boundary so testnet polling continues next cycle.
- **Handoff**: None
- **Notes**: Added live-loop handling for recoverable read timeouts with one Beijing-time log line and unknown exceptions still re-raised. The poll now fetches per-symbol features before state-changing reconciliation/open/update work, so OHLCV timeout aborts the cycle cleanly. Verified with `.venv/bin/python -m pytest tests/live/test_live_run.py -q` and `.venv/bin/python -m pytest tests/live -q`.

### 2026-07-01 - Reduce Cross-Zone Workflow Overhead
- **Status**: Completed
- **Zone**: Planning
- **Description**: Updating the zone operating model so Planning/Execution/Acceptance/Maintenance use shorter prompts and fewer handoffs by default.
- **Handoff**: None
- **Notes**: Added low-overhead defaults, short Execution/Acceptance/Maintenance cards, progressive 3-5 file read guidance, stricter `/private/tmp` handoff triggers, and a medium-change flow that avoids unnecessary Acceptance Zone prompts unless behavior/safety risk warrants them.

### 2026-07-01 - Validate Restarted Pending Setups And Trim 5m Fetch
- **Status**: Completed
- **Zone**: Execution
- **Description**: Revalidating restored live pending setups against current Hyperliquid candles and reducing 5m OHLCV fetch length without changing RSI alignment.
- **Handoff**: None
- **Notes**: Added restart validation that discards pending setups when current candles cannot rebuild the same setup/progress, and reduced 5m fetch length to Bollinger period + one forming-candle allowance. 1h/15m RSI warmup remains 500 because local Hyperliquid testnet calibration requests failed and there is no safe evidence for shortening without risking RSI alignment. Verified with `.venv/bin/python -m pytest tests/live -q`, `.venv/bin/python -m pytest tests/test_indicators.py tests/test_config.py -q`, and `.venv/bin/python -m pytest -q`.

### 2026-07-01 - Align Live RSI Method And Warmup
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding configurable RSI method and warmup bars for `bbmr_trailing_stop_v1`, using the active live exchange environment's own candles for live RSI calibration.
- **Handoff**: None
- **Notes**: Added `sma`/`wilder` RSI method support, defaulted `bbmr_trailing_stop_v1` to `wilder` with `warmup_bars: 500`, used warmup for live Hyperliquid OHLCV fetches, and added read-only `scripts/hyperliquid_rsi_calibration.py`. Verified with `.venv/bin/python -m pytest tests/live -q`, `.venv/bin/python -m pytest tests/test_indicators.py tests/test_config.py -q`, and `.venv/bin/python -m pytest`.

### 2026-07-01 - Plan Hyperliquid RSI Alignment
- **Status**: Planned
- **Zone**: Planning
- **Description**: Discussing how to align locally computed RSI with Hyperliquid chart RSI when the API does not return RSI values.
- **Handoff**: None
- **Notes**: Hyperliquid API-visible data exposes OHLCV candles but not RSI. User confirmed candles can come directly from the same Hyperliquid environment used for live/testnet, so the RSI alignment scope is formula replication plus warmup/history length calibration. Durable rule captured in ADR-003: RSI must be computed from candles fetched from the same exchange environment whose website chart is being matched; future mainnet or other exchange integrations must follow the same-source candle rule. Current `compute_rsi()` uses SMA rolling averages, while chart-style RSI is likely Wilder/RMA-based. Planning recommendation is to implement configurable RSI method/history length and validate against manually sampled Hyperliquid chart values before enabling live local-computed RSI decisions. Because this change directly affects live setup/confirmation decisions, it requires a separate Acceptance Zone review prompt.

### 2026-07-01 - Tighten Live Data Source And Restart Recovery
- **Status**: Blocked
- **Zone**: Execution
- **Description**: Evaluating the confirmed hard rule that live trading-chain indicators/prices must come directly from Hyperliquid and stale local pending setup state must not survive restart without current-data validation.
- **Handoff**: None
- **Notes**: Stopped before code changes because Hyperliquid documented/API-visible live data provides OHLCV candles/orders/fills/positions, while `bbmr_trailing_stop_v1` currently requires RSI and Bollinger values produced locally by `src/bbmr/trailing_features.py`. Per user stop condition, do not continue local-computed indicators into live trading until Planning/User confirms the minimal replacement approach.

### 2026-07-01 - Fix Live Runner Timezone Output And Completed-Candle Crash
- **Status**: Completed
- **Zone**: Execution
- **Description**: Fixing live runner tz-naive/tz-aware completed-candle comparisons, Beijing terminal display time, and duplicate per-symbol position fetches after log/output changes.
- **Handoff**: None
- **Notes**: Normalized completed-candle comparison inputs to UTC-aware timestamps, made client `now()` UTC-aware, converted only terminal display time to Asia/Shanghai, and reused `_poll_once()` positions in strategy entry guards. Verified with `.venv/bin/python -m pytest tests/live -q` and `.venv/bin/python -m pytest`.

### 2026-07-01 - Fix Live Trading Correctness P0
- **Status**: Completed
- **Zone**: Execution
- **Description**: Fixing `bbmr_trailing_stop_v1` live P0 correctness issues: new-window 15m RSI baseline, completed 5m filtering, real fill average stops, and minimal exchange position/order entry guards.
- **Handoff**: None
- **Notes**: Implemented in `src/bbmr/trailing.py`, `src/bbmr/live/trailing_runtime.py`, `src/bbmr/live/run.py`, and `src/bbmr/live/state_store.py`; added focused live tests. Verification passed with `.venv/bin/python -m pytest tests/live -q` and `.venv/bin/python -m pytest`.

### 2026-07-01 - Review Strategy Optimization Recommendations
- **Status**: Planned
- **Zone**: Planning
- **Description**: Reviewing `/Users/jeffrey/Downloads/bulin_strategy_optimization_recommendations.md` against the active `bbmr_trailing_stop_v1` consensus.
- **Handoff**: None
- **Notes**: User approved one combined execution task for live trading correctness: 15m RSI baseline window, completed 5m candle filtering, real fill average price, and minimal open-position/open-order entry guard. Defer broad API cleanup, schema migrations, fixture refactors, stop-update-time/soft-exit fields, and RSI algorithm changes until separately planned.

### 2026-07-01 - Simplify Live Runner Terminal Output
- **Status**: Completed
- **Zone**: Execution
- **Description**: Reducing Hyperliquid live runner regular terminal output from indicator dumps to concise logic-chain status.
- **Handoff**: None
- **Notes**: Removed regular indicator/exchange-position dumps from `src/bbmr/live/run.py`, aligned existing runtime event text to concise logic-chain status, and verified with `.venv/bin/python -m pytest tests/live/test_live_run.py tests/live/test_trailing_runtime.py -q` plus `.venv/bin/python -m pytest tests/live -q`.

### 2026-07-01 - Fix Hyperliquid Market Order Price Requirement
- **Status**: Completed
- **Zone**: Maintenance
- **Description**: Applying the smallest runtime-stability fix for Hyperliquid market orders after testnet live run crashed on `price=None`.
- **Handoff**: None
- **Notes**: Scope limited to maintenance-zone stability repair. Reused existing market-price fetch path in `HyperliquidClient` for both open and close market orders, added a focused regression test, and verified with `.venv/bin/python -m pytest tests/live/test_hyperliquid_client.py -q` and `.venv/bin/python -m pytest tests/live/test_trailing_runtime.py -q`.

### 2026-07-01 - Update Zone Model And Strategy Consensus
- **Status**: Completed
- **Zone**: Planning
- **Description**: Added four-zone responsibilities and updated strategy consensus for corrected 15m RSI baseline/confirmation rules.
- **Handoff**: None
- **Notes**: Added `docs/project_notes/zone_operating_model.md` for Planning/Execution/Acceptance/Maintenance zone boundaries, output formats, `/private/tmp` handoff conventions, and cross-zone interaction flow. `AGENTS.md` now points to that document instead of carrying the full zone model inline. Strategy consensus now states that 15m baseline must be the first completed 15m inside the new 1h setup window, confirmation must stay inside the same 1h window, forming 15m candles are invalid, and terminal output should focus on logic-chain status.

### 2026-06-30 - Document Active Strategy Consensus
- **Status**: Completed
- **Zone**: Planning
- **Description**: Added a shared human/AI-readable strategy consensus document for `bbmr_trailing_stop_v1`.
- **Handoff**: None
- **Notes**: Created `docs/strategy_consensus/bbmr_trailing_stop_v1.md` and updated `AGENTS.md` so all zones read it before discussing or changing active strategy/live behavior.

### 2026-06-30 - Prepare Hyperliquid Live Mainline Integration
- **Status**: Completed
- **Zone**: Execution
- **Description**: Creating a clean mainline integration branch from `main` for the minimal Hyperliquid testnet live runner loop.
- **Handoff**: None
- **Notes**: Working in `/private/tmp/bbmr_hyperliquid_live_mainline` on `feature/hyperliquid-live-mainline`. Selected live/config/script/test files only; `src/bbmr/backtest/`, `tests/backtest/`, `tests/fixtures/`, `data/`, and `reports/` are intentionally excluded. Live trailing helpers were moved to neutral modules. Verification passed with `/Users/jeffrey/Documents/布林带策略/.venv/bin/python -m pytest tests/live -q` (`46 passed`) and `/Users/jeffrey/Documents/布林带策略/.venv/bin/python -m pytest` (`122 passed`).

### 2026-06-26 - Execute BBMR v3.2 Phase 1C Decision Chain
- **Status**: Completed
- **Zone**: Execution
- **Description**: Executing `/private/tmp/bbmr_phase1C_decision_chain_handoff.md` after confirming Phase 1A/1B tests pass.
- **Handoff**: `/private/tmp/bbmr_phase1C_decision_chain_handoff.md`
- **Notes**: Implemented allowed Phase 1C files only. Verification passed with `python -m pytest` and `python -m pytest --cov=bbmr` using the project `.venv`.

### 2026-06-25 - Execute BBMR v3.2 Phase 1B State Storage
- **Status**: Completed
- **Zone**: Execution
- **Description**: Executing `/private/tmp/bbmr_phase1B_state_storage_handoff.md` after confirming Phase 1A tests pass.
- **Handoff**: `/private/tmp/bbmr_phase1B_state_storage_handoff.md`
- **Notes**: Implemented Phase 1B allowlisted files only. Verification passed with `python -m pytest` and `python -m pytest --cov=bbmr` using the project `.venv`.

### 2026-06-25 - Execute BBMR v3.2 Phase 1A Core Scaffold
- **Status**: Completed
- **Zone**: Execution
- **Description**: Executing `/private/tmp/bbmr_phase1A_core_scaffold_handoff.md` for the Phase 1A standalone `bbmr` package scaffold.
- **Handoff**: `/private/tmp/bbmr_phase1A_core_scaffold_handoff.md`
- **Notes**: Implemented the Phase 1A allowlisted package/config/test files. Verification passed with `python -m pip install -e ".[dev]"`, `python -m pytest`, and `python -m pytest --cov=bbmr` using the project `.venv` on Python 3.12.

### 2026-06-25 - Prepare GitHub Push
- **Status**: Completed
- **Zone**: Execution
- **Description**: Added `.gitignore`, prepared repository remote for `Jeffrey22444/bulin-strategy`, and removed `.DS_Store` files from version control.
- **Handoff**: None
- **Notes**: `gh` CLI is not installed, so publish will use direct `git` commands.

### 2026-06-25 - Initialize Project Memory System
- **Status**: Completed
- **Zone**: General
- **Description**: Created `AGENTS.md` and `docs/project_notes/` memory files for bugs, decisions, key facts, and worklog.
- **Handoff**: None
- **Notes**: Added planning-zone and execution-zone protocols. Future agents should actively update this worklog.
