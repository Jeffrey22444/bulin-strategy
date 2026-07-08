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

### 2026-07-08 - OPS-1 Safety Severity Journal
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding minimal WARN/ERROR/CRITICAL terminal and SQLite journal evidence for existing live safety paths.
- **Handoff**: None
- **Notes**: Added terminal severity prefixes and `payload_json.severity` for recoverable network errors, entry slippage exceeded, entry order not confirmed, protective stop failures, and `entry_unprotected`. Added read-only `scripts/live_safety_journal.py` to print recent WARN/ERROR/CRITICAL journal rows. Scope stayed limited to existing safety states and journal payloads; no DB schema, mainnet unlock, client order IDs/tags, startup reconcile, external alerts, strategy signal, sizing, stop, or TP changes. Verified with `.venv/bin/python -m pytest tests/live/test_trailing_runtime.py tests/live/test_live_run.py tests/live/test_state_store.py tests/live/test_live_safety_journal.py -q`.

### 2026-07-08 - Strategy Entry Execution Quality Guard
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding pre-entry quote/spread checks and post-fill slippage journaling for real Hyperliquid strategy market entries.
- **Handoff**: None
- **Notes**: Current dirty `main` is treated as the accepted SAFETY-1 through SAFETY-7 baseline per worklog and user instruction. Added `execution.max_market_spread_bps` and `execution.max_entry_slippage_bps`; real strategy entries now block before `set_leverage()` when quote data is missing/invalid or spread is too wide, and record `entry_slippage_exceeded` when a confirmed fill deviates from the pre-entry quote reference. Scope stayed limited to new strategy market entries; no changes to signals, sizing, stop/TP formulas, manual reconcile, or mainnet gate. Verified with `.venv/bin/python -m pytest tests/live/test_hyperliquid_client.py tests/live/test_trailing_runtime.py tests/live/test_live_config.py -q`, `.venv/bin/python -m pytest tests -q`, and `git diff --check`.

### 2026-07-08 - Mainnet Deferred Safety Backlog
- **Status**: Planned
- **Zone**: Planning
- **Description**: Recording safety work that should be handled before enabling real mainnet orders, but does not need to block current Hyperliquid testnet iteration.
- **Handoff**: None
- **Notes**: Before mainnet unlock, re-read this entry plus `docs/strategy_consensus/bbmr_trailing_stop_v1.md` and the external safety audit. Deferred items: add exchange-side system order identity (`clientOrderId`/tag/prefix where Hyperliquid/ccxt supports it) for entries and protective stops; add startup reconciliation that compares local SQLite state with exchange positions/open orders and enters an explicit reconciliation-required state on mismatch; finish unknown order lifecycle recovery for network/API failures after order submission; add market execution sanity guards for spread/orderbook depth/slippage/fill sanity; replace the current hardcoded mainnet order block with a deliberate multi-gate unlock only after the above checks pass. Do not treat the disabled 15m RSI reversal as a safety vulnerability by itself; that remains a strategy choice.

### 2026-07-08 - Strategy Entry Balance Safety Guard
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding pre-order equity and available-margin guards before live strategy entries.
- **Handoff**: None
- **Notes**: Current mixed worktree is treated as the accepted baseline through SAFETY-6. `_poll_once()` now passes full balance into `maybe_open_strategy_trade()`, which blocks new strategy entries when equity is non-positive or available margin is below proposed margin. Existing position management, stop/TP, manual reconcile, sizing formula, and global notional cap semantics stay unchanged. Verified with `.venv/bin/python -m pytest tests/live/test_trailing_runtime.py tests/live/test_live_run.py tests/live/test_live_config.py -q` and `.venv/bin/python -m pytest tests -q`.

### 2026-07-08 - SAFETY-6 Manual Position Config Gates
- **Status**: Completed
- **Zone**: Execution
- **Description**: Making `adopt_manual_positions` and `manage_full_manual_added_size` actually gate manual position adoption and manual size-change management.
- **Handoff**: None
- **Notes**: Current mixed worktree is treated as the accepted baseline from previous safety tasks. `reconcile_symbol()` now skips unknown manual position adoption when `adopt_manual_positions=false`, and skips manual size/entry merge updates when `manage_full_manual_added_size=false`; SAFETY-4 `entry_unprotected` recovery remains active. Verified with `.venv/bin/python -m pytest tests/live/test_live_config.py tests/live/test_trailing_runtime.py tests/live/test_live_run.py -q`.

### 2026-07-08 - SAFETY-5 Global Notional Risk Cap
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding a live strategy-entry guard that blocks new entries when existing exchange notional plus proposed strategy notional exceeds the configured account-equity cap.
- **Handoff**: None
- **Notes**: User confirmed the current mixed worktree is an accepted baseline from other windows. Added `execution.max_total_notional_fraction` defaulting to `1.0`; `maybe_open_strategy_trade()` now blocks only new strategy entries when all exchange positions plus proposed strategy notional exceed the cap. Existing management, stop/TP/manual handling, and sizing formulas stay unchanged. Verified with `.venv/bin/python -m pytest tests/live/test_live_config.py tests/live/test_trailing_runtime.py -q` and `.venv/bin/python -m pytest tests`.

### 2026-07-08 - SAFETY-4 Entry Lifecycle Minimal State Machine
- **Status**: Completed
- **Zone**: Execution
- **Description**: Hardening strategy entry lifecycle so `status=open` is only written after exchange position confirmation and protective stop creation.
- **Handoff**: None
- **Notes**: User confirmed existing mixed worktree changes belong to other windows and may be treated as current baseline. Real order entry now confirms same symbol/side exchange position before creating a local trade, stores stop-failure fills as `entry_unprotected`, and promotes them to `open` only after reconcile creates a protective stop. Verified with `.venv/bin/python -m pytest tests/live/test_trailing_runtime.py tests/live/test_state_store.py -q` and `.venv/bin/python -m pytest tests`.

### 2026-07-08 - Special State Terminal Marker
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding a simple terminal marker to every managed-position poll while adverse-slope TP special state is active.
- **Handoff**: None
- **Notes**: Managed-position output now prefixes the existing status/stop-update line with `[SPECIAL]` while `adverse_slope_tp_active` is true. No strategy, TP trigger, stop, sizing, or persistence behavior changed. Verified with `.venv/bin/python -m pytest tests/live/test_live_run.py -q`.

### 2026-07-08 - SAFETY-3 Close Lifecycle Verification
- **Status**: Completed
- **Zone**: Execution
- **Description**: Hardening adverse-slope TP close cleanup so local stop cancellation and archive only happen after the exchange confirms the same symbol/side position is zero.
- **Handoff**: None
- **Notes**: `maybe_close_adverse_slope_take_profit()` now submits the reduce-only market close, fetches exchange positions, and only cancels the system stop/archives after the same symbol+side position is absent or zero. If the same side remains, local `qty` is updated and `_replace_stop()` keeps protection; close/fetch failures keep the trade open. Verified with `.venv/bin/python -m pytest tests/live/test_trailing_runtime.py tests/live/test_live_run.py -q`.

### 2026-07-08 - Acceptance Scope For User Manual Edits
- **Status**: Completed
- **Zone**: General
- **Description**: Recorded a project-local acceptance rule for user-declared manual config or strategy edits.
- **Handoff**: None
- **Notes**: When the user explicitly says a specific config or strategy change was manually made by them and is outside the current execution scope, Acceptance Zone should treat it as user-owned and not fail on that point alone unless the user asks to include manual edits in scope.

### 2026-07-08 - SAFETY-2 Protective Stop Replacement Fail-Safe
- **Status**: Completed
- **Zone**: Execution
- **Description**: Hardening protective stop replacement so local state is not marked safe when a new reduce-only stop fails, and strategy entries are blocked after a replacement safety failure.
- **Handoff**: None
- **Notes**: `_replace_stop()` now creates the new reduce-only stop and validates a real order id before cancelling the old system stop; missing/`None` ids and create failures append `protective_stop_failed`, keep local stop state unchanged, and set a runtime emergency flag that blocks later strategy entries. Also stopped touching exchange stops when `allow_orders` is false. Verified with `.venv/bin/python -m pytest tests/live/test_trailing_runtime.py tests/live/test_live_run.py -q`. No full entry lifecycle state machine, stop formula change, TP close verification, sizing change, or mainnet unlock.

### 2026-07-08 - SAFETY-1 Live Stop Completed Candle And Runner Lock
- **Status**: Completed
- **Zone**: Execution
- **Description**: Fixing two live execution safety issues: managed stop updates must use latest completed 1h candles, and live runner startup must reject a second simultaneous instance.
- **Handoff**: None
- **Notes**: Managed-position stop updates now require both latest completed `1h` and latest completed `5m` rows; otherwise the runner prints the normal waiting status and skips stop update for the poll. Added a stdlib `fcntl.flock` single-instance lock in the live storage directory so a second runner fails before client/runtime startup. Verified with `.venv/bin/python -m pytest tests/live/test_live_run.py tests/live/test_trailing_runtime.py -q`. No changes to entry strategy, sizing, TP/stop formulas, mainnet gate, stop replacement state machine, or manual position handling.

### 2026-07-08 - Adjust Live Entry Sizing For Adverse Slope
- **Status**: Completed
- **Zone**: Execution
- **Description**: Changing `bbmr_trailing_stop_v1` live entry sizing to default `15% * 3x`, with `15% * 2x` when the entry-side adverse-slope TP state is active at entry.
- **Handoff**: None
- **Notes**: Set live margin fraction to `0.15`, added `execution.adverse_slope_leverage = 2`, and selected per-entry leverage from the current symbol/side's completed-1h adverse-slope state. `entry_notional` and `set_leverage()` now share the selected leverage for strategy entry only. No changes to existing positions, manual handling, stops, TP trigger behavior, or safety gates. Verified with `.venv/bin/python -m pytest tests/live/test_live_config.py tests/live/test_trailing_runtime.py tests/test_config.py -q`.

### 2026-07-07 - Implement Adverse Slope Midband Take Profit
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding a strategy-only adverse 1h middle-band slope active take-profit path in parallel with the trailing-stop chain.
- **Handoff**: None
- **Notes**: Created branch `codex/adverse-slope-midband-take-profit`; added config, minimal live trade state, strategy-only active/clear/trigger runtime behavior, consensus docs, and focused tests. Acceptance follow-up fixed completed-1h-only evaluation and full field clearing on inactive state. Verified with `.venv/bin/python -m pytest tests/test_config.py tests/live/test_trailing_runtime.py tests/live/test_state_store.py tests/live/test_live_run.py -q`.

### 2026-07-07 - Plan Adverse Slope Midband Take Profit
- **Status**: Planned
- **Zone**: Planning
- **Description**: Planning a parallel active take-profit path for positions opened against a strong 1h middle-band slope.
- **Handoff**: None
- **Notes**: User-approved direction: keep RSI thresholds unchanged; add an `adverse_slope_take_profit` strategy config with `enabled`, `slope_n`, `slope_threshold_pct`, and `near_middle_frac` defaulting to `0.0`. Special state is evaluated at entry and then only once per new completed 1h bucket. While active, each 30s managed-position poll checks live price against the midband-derived TP and may close market; when the next 1h bucket no longer satisfies adverse-slope conditions, the special TP state must be cleared so normal trailing-stop logic is not polluted.

### 2026-07-07 - Implement Hourly Midband Follow Refresh
- **Status**: Completed
- **Zone**: Execution
- **Description**: Limit `trailing_stage >= 3` midband-follow stop refreshes to once per 1h bucket.
- **Handoff**: None
- **Notes**: Added `midband_follow_bucket_start` persistence for open trades and limited stage-3 midband-follow refresh to activation plus the first relevant poll in each new 1h bucket. Same-bucket 30s polls no longer refresh the midband stop, while stage 4 still works. Verified with `.venv/bin/python -m pytest tests/live/test_trailing_runtime.py tests/live/test_state_store.py -q`.

### 2026-07-07 - Plan Coarser Midband Follow Stop Refresh
- **Status**: Planned
- **Zone**: Planning
- **Description**: Reviewing whether midband-follow trailing stops should stop refreshing every 30 seconds and instead update on a coarser cadence.
- **Handoff**: None
- **Notes**: Current runtime path calls `update_stop()` from the 30s poll loop and passes `features[0].iloc[-1]` as the 1h row, which can cause repeated midband-follow stop refreshes within the same 1h window. Planning direction: prefer freezing the midband-follow stop within the current 1h bucket and only refreshing from the next completed/opened 1h bucket, instead of arbitrary 10m/20m/30m intra-hour refreshes that depend on forming 1h values.

### 2026-07-06 - Implement Dynamic Midband Follow Trailing Stop
- **Status**: Completed
- **Zone**: Execution
- **Description**: Updating `bbmr_trailing_stop_v1` trailing stop chain so step 2 moves to entry and step 3 persists a midband-follow state.
- **Handoff**: None
- **Notes**: Added `trailing_stage` persistence on open trades, changed step 2 to entry price, and made step 3 activate persisted midband-follow using the latest completed 1h middle with entry-price floor/ceiling. Verified with `.venv/bin/python -m pytest tests/live/test_trailing_runtime.py tests/live/test_state_store.py -q`.

### 2026-07-06 - Plan Dynamic Midband Follow Trailing Stop
- **Status**: Planned
- **Zone**: Planning
- **Description**: Planning a revised trailing-stop chain where the second step moves to breakeven and the third step activates dynamic following of the latest completed 1h middle band.
- **Handoff**: None
- **Notes**: User-approved behavior: keep first and fourth trailing triggers as-is; second trigger keeps `5m close > 1h middle` but candidate stop becomes entry price; third trigger keeps `5m high >= midpoint(1h middle, 1h upper)` for long / symmetric short trigger, then activates a persistent midband-follow mode. In midband-follow mode long stop follows `max(latest completed 1h middle, entry_price)`, short follows `min(latest completed 1h middle, entry_price)`, allowing midband stop relaxation while preventing a return to loss after stage 3. This requires minimal persistent stage/state, not just a stateless candidate calculation.

### 2026-07-06 - Inspect SOL Repeated Stop Updates
- **Status**: Completed
- **Zone**: Maintenance
- **Description**: Reviewed recent SOL trade events after repeated upward stop moves were observed during the same evening session.
- **Handoff**: None
- **Notes**: Local SQLite shows one SOL long trade opened at `2026-07-05T03:45:00+00:00` with stop updates at `08:45:18`, `12:30:04`, `12:30:40`, `12:31:16`, and `12:31:53` UTC before exit at `13:00:39` UTC. The configured `first_step_risk_reduction` only changes the first trailing candidate, but the final stored stop (`80.389775`) exceeded entry (`80.1398`), so later updates were not just the softened first step. Strongest code-level suspicion is repeated recalculation against `features[0].iloc[-1]` in `src/bbmr/live/run.py` while using the latest completed 5m row, which could allow stop moves every ~30s if the fetched 1h frame's last row is the still-forming candle.

### 2026-07-05 - Soften First Trailing Stop Step
- **Status**: Completed
- **Zone**: Execution
- **Description**: Add a configurable first-step risk reduction for `bbmr_trailing_stop_v1` so the first trailing stop move can reduce initial risk instead of always moving to entry.
- **Handoff**: None
- **Notes**: Added `trailing_stop.first_step_risk_reduction` with default `1.0`, set current trailing strategy YAML to `0.5`, and changed only the first trailing-stop candidate to reduce initial risk by that ratio. Verified with `.venv/bin/python -m pytest tests/test_config.py tests/live/test_trailing_runtime.py -q`.

### 2026-07-04 - Make 15m RSI Reversal Confirmation Configurable
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding a bbmr_trailing_stop_v1 YAML switch so live entry can optionally skip the 15m RSI reversal confirmation layer.
- **Handoff**: None
- **Notes**: Added `entry_confirmation.require_15m_rsi_reversal` to trailing strategy config with default `true`, set current YAML to `false`, and updated live runtime to skip directly to 5m entry when disabled. Updated consensus docs and verified with `.venv/bin/python -m pytest tests/test_config.py tests/live/test_trailing_runtime.py -q`.

### 2026-07-04 - Improve Workflow Docs From Desktop Pet Reference
- **Status**: Completed
- **Zone**: Maintenance
- **Description**: Compared `Desktop_pet` workflow docs against this project and applied minimal documentation upgrades to zone guidance.
- **Handoff**: None
- **Notes**: Added `Zone Defaults` to `AGENTS.md`; expanded `zone_operating_model.md` with stronger low-overhead defaults, Acceptance Contract, execution-vs-acceptance split, zone identity guidance, and reusable zone opening prompts; added ADR-004 to record the execution-evidence and acceptance-review separation.

### 2026-07-04 - Brainstorm Entry Timing Tradeoffs
- **Status**: Planned
- **Zone**: Planning
- **Description**: Discussing whether the current 15m RSI reversal plus 5m price confirmation is too conservative and causes late entries after a 1h setup.
- **Handoff**: None
- **Notes**: Explore minimal strategy variants that preserve fake-breakout protection while improving entry price. Early direction: compare current confirm-then-enter chain against simpler alternatives such as staged entry, pullback-after-confirm entry, early probe plus confirmation add/keep, or replacing one confirmation layer instead of stacking both 15m RSI and 5m price confirmation.

### 2026-07-04 - Plan Stop Order Slippage Control
- **Status**: Planned
- **Zone**: Planning
- **Description**: Discussing whether live trailing stops should use limit-style protection after observed breakeven stop fills more than 1% away from stop price.
- **Handoff**: None
- **Notes**: Current Hyperliquid client creates reduce-only stop-market orders via `create_reduce_only_stop()`. Recommendation is not to blindly replace protective stops with passive limit orders, because limit stops can fail to fill. First planning direction: inspect actual fill/order records, then consider configurable stop execution modes such as `market` default and optional aggressive stop-limit with slippage band plus fallback/alert behavior.

### 2026-07-03 - Inspect Live Runtime Log And SQLite Growth
- **Status**: Completed
- **Zone**: Maintenance
- **Description**: Checked whether the overnight live trading run accumulated excessive logs or SQLite data.
- **Handoff**: None
- **Notes**: `data/live/hyperliquid_testnet.sqlite3` was only `36K` with `37` total `live_trade_events`, `0` open trades, and `0` pending setups. `23` events were created in the last 12 hours, which is consistent with state-change journaling rather than per-poll logging. No SQLite `-wal` or `-shm` growth files were present. The only `.log` file found was the older soak-test artifact `data/live/soak/20260701T200829/live.log` at `30K`; current live runner output is terminal-only and the SQLite journal stores only state transitions.

### 2026-07-02 - Generate Reusable Workflow Architecture Handoff
- **Status**: Completed
- **Zone**: Planning
- **Description**: Created a generic handoff for bootstrapping the same multi-zone workflow and Project Memory system in a new unrelated project.
- **Handoff**: `/private/tmp/desktop_pet_project_workflow_architecture_handoff_20260702.md`
- **Notes**: Handoff intentionally excludes trading-system business content and keeps only reusable workflow architecture, zone responsibilities, cross-zone interaction rules, Project Memory setup, and desktop-pet-specific product-consensus suggestions.

### 2026-07-02 - Plan Idle-Aware Live Poll Scheduler
- **Status**: Planned
- **Zone**: Planning
- **Description**: Reviewing `/Users/jeffrey/Downloads/bbmr_idle_scheduler_b_plan_task.md` for reducing full live polls while idle.
- **Handoff**: None
- **Notes**: User clarified the outer loop should still wake on a 30s cadence; only the work done per tick changes. Idle ticks should run lightweight position/open-order guards only, while full OHLCV strategy polls are due at startup, when active state exists, or at the next 1h close plus grace. This change must be implemented on a new branch, not directly on the current branch/main. Acceptance must focus on full-poll-vs-light-guard state transitions, not on literally sleeping for one hour. Do not change strategy rules, safety gates, persistence schema, or introduce external scheduler dependencies.

### 2026-07-02 - Implement Idle-Aware Live Poll Scheduler
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding idle/full tick scheduling to the Hyperliquid live runner so idle state uses light guards and aligns full strategy polls to 1h candle close plus grace.
- **Handoff**: `/Users/jeffrey/Downloads/bbmr_idle_scheduler_b_plan_task.md`
- **Notes**: Implemented on branch `codex/idle-aware-live-poll-scheduler`. User approved carrying the existing local `configs/live_hyperliquid_testnet.yaml` margin change into this branch. Added idle scheduler config fields, startup full poll, idle light guard without OHLCV, 1h+grace full-poll alignment, active-state 30s full polling, and recoverable network handling for light guard. Verified with `.venv/bin/python -m pytest tests/live/test_live_config.py tests/live/test_live_run.py tests/live/test_trailing_runtime.py -q` and `.venv/bin/python -m pytest tests/live -q`.

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
