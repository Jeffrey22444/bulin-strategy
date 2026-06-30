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

### 2026-06-30 - Add Exit-Time Exchange PnL Archive Attempt
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding minimal Hyperliquid live exit-time realized PnL lookup before archiving disappeared positions.
- **Handoff**: None
- **Notes**: Added a small `HyperliquidClient.fetch_recent_realized_pnl()` wrapper around recent user trades and a runtime archive helper that records exchange PnL when available, otherwise archives with `pnl_source=unknown`. Verification passed with `.venv/bin/python -m pytest tests/live -q` (`42 passed`).

### 2026-06-30 - Plan Live PnL Reconciliation Scope
- **Status**: Planned
- **Zone**: Planning
- **Description**: Deciding whether Hyperliquid live runner should fetch exchange realized PnL for future review stats.
- **Handoff**: None
- **Notes**: Current persistence already has `realized_pnl`, `fees`, and `pnl_source`, but runtime archives exits as `unknown`. User approved a minimal exit-time exchange reconciliation only, not every-poll trade-history syncing. For simple scoped changes like this, planning should provide only an execution prompt; no separate acceptance prompt is needed if execution tests pass.

### 2026-06-30 - Add Live Setup Persistence And Journal
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding minimal SQLite persistence for live pending setups/15m confirmation state and append-only live event journal.
- **Handoff**: None
- **Notes**: Added `live_pending_setups`, `live_trade_events`, and small future-stat fields on `live_trades`. `LiveRuntime` restores unexpired setups on startup, persists create/confirm/expire/entry cleanup, and writes journal rows only for state changes. Verification passed with `.venv/bin/python -m pytest tests/live -q` (`39 passed`) and `.venv/bin/python -m pytest` (`180 passed`).

### 2026-06-30 - Plan Live Persistence Scope
- **Status**: Planned
- **Zone**: Planning
- **Description**: Deciding the minimal persistence model for Hyperliquid live runner setup recovery, trade journal, and future review stats.
- **Handoff**: None
- **Notes**: Acceptance report `/private/tmp/live_persistence_acceptance_handoff_20260630.md` found current in-memory setup state works only during one uninterrupted process lifetime, and current SQLite `live_trades` is an open-position store rather than a review/stat ledger. User approved the minimal direction: persist pending setup/15m confirmation state across restart, keep `live_trades` for open-position management, add append-only journal, and write only on state changes instead of every poll.

### 2026-06-30 - Fix Stale Live Stop Cancel Crash
- **Status**: Completed
- **Zone**: Execution
- **Description**: Fixing live runner crash when a local open trade references a stale system stop order but the exchange position is already gone.
- **Handoff**: None
- **Notes**: `_cancel_system_stop()` now tolerates only missing/stale order errors such as `OrderNotFound: Order was never placed, already canceled, or filled`, allowing reconciliation to archive the trade as `manual_or_exchange_closed`. Verification passed with `.venv/bin/python -m pytest tests/live -q` (`33 passed`) and `.venv/bin/python -m pytest` (`174 passed`).

### 2026-06-30 - Add Live Env Credential Loading
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding minimal `.env` credential loading for Hyperliquid live runner and acceptance script without changing trading behavior.
- **Handoff**: None
- **Notes**: Added stdlib-only `.env` loader used by `python -m bbmr.live.run` and `scripts/hyperliquid_acceptance.py`, plus `.env.example` placeholders. Loader preserves already-exported variables. Verification passed with `.venv/bin/python -m pytest tests/live -q` (`31 passed`) and `.venv/bin/python -m pytest` (`172 passed`); `.env` remains ignored by Git.

### 2026-06-30 - Fix Live Runner Acceptance Failures
- **Status**: Completed
- **Zone**: Execution
- **Description**: Fixing the three scoped Hyperliquid live runner acceptance failures: poll-loop stop maintenance, strict strategy config path lock, and terminal observability output.
- **Handoff**: `/private/tmp/hyperliquid_live_runner_acceptance_handoff_20260630.md`
- **Notes**: `_poll_once()` now reconciles, loads features, maintains trailing stops for existing managed trades, and prints required candle/indicator/position/local-state fields. Live config now hard-locks to canonical `configs/strategy_bbmr_trailing_stop_v1.yaml`, accepting equivalent absolute/`./` paths but rejecting copied or alternate trailing YAMLs. Verification passed with `.venv/bin/python -m pytest tests/live -q` (`27 passed`) and `.venv/bin/python -m pytest` (`168 passed`).

### 2026-06-30 - Plan Live Runner Acceptance Fix
- **Status**: Planned
- **Zone**: Planning
- **Description**: Planning the minimal fix after Hyperliquid live runner acceptance failed.
- **Handoff**: None
- **Notes**: Acceptance found three scoped issues: main poll loop does not call trailing stop maintenance, live strategy config is not strictly locked to `configs/strategy_bbmr_trailing_stop_v1.yaml`, and terminal observability output is incomplete. Planning recommendation is a short execution prompt, not a full handoff.

### 2026-06-30 - Execute Hyperliquid Testnet Live Runner
- **Status**: Completed
- **Zone**: Execution
- **Description**: Executing `/private/tmp/hyperliquid_testnet_live_runner_handoff_20260630.md` for a terminal-only Hyperliquid testnet runner for `bbmr_trailing_stop_v1`.
- **Handoff**: `/private/tmp/hyperliquid_testnet_live_runner_handoff_20260630.md`
- **Notes**: Added isolated `src/bbmr/live` config/client/store/runtime/CLI, testnet live config, deterministic acceptance script, fake-exchange tests, and `ccxt==4.5.58`. Verification passed with `.venv/bin/python -m pytest` (`165 passed`) and `tests/live` (`24 passed`); dry-run smoke passed without credentials; real testnet acceptance was not run because required Hyperliquid credential environment variables are absent.

### 2026-06-30 - Plan Hyperliquid Testnet Integration
- **Status**: In Progress
- **Zone**: Planning
- **Description**: Discussing a testnet-first live validation path for `bbmr_trailing_stop_v1`, with a future mainnet switch interface and reference to `/Users/jeffrey/Documents/AI_trading/opennof1`.
- **Handoff**: `/private/tmp/hyperliquid_testnet_live_runner_handoff_20260630.md`
- **Notes**: Planning only. Current recommendation is to reuse only the minimal exchange-boundary patterns from `opennof1`: credentials model, logical/exchange symbol mapping, market polling, trader wrapper, deterministic acceptance script, and fake-exchange tests. User clarified first live phase should allow Hyperliquid testnet orders, use 10% account equity per entry with 3x leverage, disallow strategy add-ons, adopt manually opened positions into trailing-stop management, close/archive system records when positions disappear manually, keep terminal-only status reporting for now, and keep strategy YAML tunable for Hyperliquid RSI/chart semantics. Additional locked boundaries: default do not cancel or replace user-created manual orders; after user manual add-on, manage the merged full position; accept exchange stop orders triggering intrabar instead of waiting for candle close. Effective strategy config must be `configs/strategy_bbmr_trailing_stop_v1.yaml`, acceptance must verify no `strategy_bbmr_v3_2.yaml` filters affect decisions. Live rolling-stop high/low restoration: for long, if latest 5m high >= midpoint(1h middle, 1h upper), set stop to 1h middle; if latest 5m high > 1h upper, set stop to latest 5m close. For short, apply the symmetric low-side rules.

### 2026-06-29 - Start New Planning Zone
- **Status**: In Progress
- **Zone**: Planning
- **Description**: Restored planning-zone context from `/private/tmp/bbmr_new_planning_zone_handoff_20260629.md`.
- **Handoff**: `/private/tmp/bbmr_new_planning_zone_handoff_20260629.md`
- **Notes**: This zone should discuss, inspect, and prepare execution/acceptance prompts only after user agreement; it should not directly edit production strategy code.

### 2026-06-29 - Configure Trailing Initial Stop Percent
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding a YAML-configurable `initial_stop_pct` for `bbmr_trailing_stop_v1` independent and shared trailing runners.
- **Handoff**: None
- **Notes**: Added trailing-stop config model/YAML field, wired independent/shared runners to config value with 0.02 fallback, and added focused tests for configured percent, validation, shared runner use, and default compatibility. Verification passed with `.venv/bin/python -m pytest` and `.venv/bin/python -m pytest --cov=bbmr`.

### 2026-06-29 - Fix Same-Setup Reentry Reconfirmation
- **Status**: Completed
- **Zone**: Execution
- **Description**: Fixing `bbmr_trailing_stop_v1` so second same-setup entry after `initial_stop_5m_close` requires a new 15m confirmation after the first exit.
- **Handoff**: `/private/tmp/shared_portfolio_reentry_reconfirm_fix_task_20260629.md`
- **Notes**: Added `confirmation_after` reset for independent/shared trailing runners, preserving original setup baseline RSI while requiring new 15m confirmation and fresh 5m entry for the second attempt. Verification passed with `.venv/bin/python -m pytest` and `.venv/bin/python -m pytest --cov=bbmr`.

### 2026-06-29 - Add Shared Trailing Portfolio Mode
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding `--portfolio-mode shared` for `bbmr_trailing_stop_v1` so multiple symbols run against one shared account instead of concatenated independent accounts.
- **Handoff**: None
- **Notes**: Added shared trailing portfolio runner, CLI `--portfolio-mode independent|shared`, shared report engine, and focused tests for portfolio equity, sizing, simultaneous symbols, same-symbol/setup reuse, and old-strategy rejection. Verification passed with `.venv/bin/python -m pytest` and `.venv/bin/python -m pytest --cov=bbmr`.

### 2026-06-29 - Fix Trailing Report Engine Field
- **Status**: Completed
- **Zone**: Execution
- **Description**: Fixing report `engine` fields so `summary.csv` and `run_metadata.json` reflect the actual old/manual or trailing event-loop path.
- **Handoff**: None
- **Notes**: Added report-layer engine mapping and CLI assertions for old/manual and trailing report outputs. Verification passed with `.venv/bin/python -m pytest tests/backtest/test_cli.py tests/backtest/test_trailing_event_loop.py`.

### 2026-06-29 - Execute Trailing Stop V1 Strategy Update
- **Status**: Completed
- **Zone**: Execution
- **Description**: Executing `/private/tmp/bbmr_trailing_stop_v1_strategy_update_handoff.md` to add isolated `bbmr_trailing_stop_v1` config, features, event loop, CLI routing, and timing tests.
- **Handoff**: `/private/tmp/bbmr_trailing_stop_v1_strategy_update_handoff.md`
- **Notes**: Added isolated trailing-stop config, feature builder, event loop, CLI route, and timing tests. Created and switched to `feature/bbmr-trailing-stop-v1` from `feature/manual-event-loop-backtest`. Verification passed with `.venv/bin/python -m pytest`, `.venv/bin/python -m pytest --cov=bbmr`, and a smoke report at `/private/tmp/bbmr_trailing_stop_v1_smoke_20260629`.

### 2026-06-27 - Add Entry Filter Switches
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding config switches so volume_ratio and range_allowed can be computed normally but skipped as entry signal filters.
- **Handoff**: None
- **Notes**: Added volume/range entry filter switches, default-on legacy behavior, YAML defaults disabled, and signal-only switch application. `./.venv/bin/python -m pytest` passed with 100 tests. Also made one exit-rule test follow current YAML thresholds without changing exit rule code.

### 2026-06-26 - Add Band Walking Config Switch
- **Status**: Completed
- **Zone**: Execution
- **Description**: Adding a minimal `band_walking.enabled` switch so config can disable lower/upper band walking filters.
- **Handoff**: None
- **Notes**: Added `band_walking.enabled` default true, set strategy YAML to false, and made lower/upper walking output all False when disabled. Re-run after manual YAML edits: `tests/test_config.py tests/test_market_state.py` passed; full `python -m pytest` has one unrelated signal/volume threshold failure in `tests/test_signals.py::test_long_signal_requires_all_filters`.

### 2026-06-26 - Execute BBMR Manual Event Loop Backtest
- **Status**: Completed
- **Zone**: Execution
- **Description**: Executing `/private/tmp/bbmr_backtest_manual_event_loop_handoff.md` on branch `feature/manual-event-loop-backtest`.
- **Handoff**: `/private/tmp/bbmr_backtest_manual_event_loop_handoff.md`
- **Notes**: Implemented local CSV manual event-loop backtest on `feature/manual-event-loop-backtest`. Verification passed with `python -m pytest` and `python -m pytest --cov=bbmr`; sample report written to `reports/backtests/manual_event_loop_smoke_20260626/`.

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
