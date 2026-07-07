# BBMR Trailing Stop V1 Strategy Consensus

This document is the shared strategy reference for humans and AI agents.

When any zone discusses `bbmr_trailing_stop_v1`, Hyperliquid live behavior, RSI/Bollinger timing, entry confirmation, trailing stops, manual position handling, or related acceptance criteria, read this file before making recommendations or code changes.

## Source Of Truth

- Active strategy config: `configs/strategy_bbmr_trailing_stop_v1.yaml`
- Active live config: `configs/live_hyperliquid_testnet.yaml`
- Strategy helpers: `src/bbmr/trailing.py`
- Live execution runtime: `src/bbmr/live/trailing_runtime.py`
- Feature builder: `src/bbmr/trailing_features.py`

Do not infer live strategy behavior from `configs/strategy_bbmr_v3_2.yaml` or old `bbmr_v3_2` filters.

## Current Purpose

The current goal is to run a Hyperliquid testnet live trading system for `bbmr_trailing_stop_v1`, then use live observations to decide later mainnet adjustments.

Backtest results are not the authority for the current strategy because prior validation found data/indicator/timing mismatch against Hyperliquid chart behavior.

## Timeframes

- `1h`: setup timeframe.
- `15m`: RSI reversal confirmation timeframe.
- `5m`: entry and trailing-stop maintenance timeframe.

The system works from completed candles. A 5m loop time represents the close time of the latest completed 5m candle.

Never use a forming `15m` candle for RSI baseline or RSI reversal confirmation.

## Indicators

- Bollinger Bands:
  - period: `20`
  - standard deviation multiplier: `2.0`
- RSI:
  - period: `14`
  - method: `wilder`
  - warmup/history bars: `500`
  - oversold: `31`
  - overbought: `69`

For live use, RSI must be computed from candles fetched from the same exchange environment whose chart is being matched. Hyperliquid testnet uses Hyperliquid testnet candles; Hyperliquid mainnet uses Hyperliquid mainnet candles.

## Entry Confirmation

- `entry_confirmation.require_15m_rsi_reversal` controls whether the 15m RSI reversal layer is required after a 1h setup.
- Current `configs/strategy_bbmr_trailing_stop_v1.yaml` sets it to `false`, so live entry skips the 15m baseline/reversal gate and waits directly for the completed 5m entry candle after a valid 1h setup.
- When set to `true`, the 15m baseline/reversal rules below apply unchanged.

## Long Setup Chain

1. Use the latest completed `1h` candle.
2. A long setup exists when:
   - `1h close < 1h lower Bollinger band`
   - `1h RSI14 < oversold`
3. The setup trigger time is the close time of that `1h` candle.
4. The setup expires one hour after trigger time.
5. After trigger time, wait for the first completed `15m` candle inside the new `1h` setup window.
6. Capture that first new-hour completed `15m RSI14` as the baseline RSI.
7. Do not use the previous `1h` window's last `15m` candle as baseline.
8. Wait for a later completed `15m` candle inside the same `1h` setup window.
9. Long confirmation occurs when that later `15m RSI14` is greater than the baseline RSI.
10. Confirmation may only use the 2nd, 3rd, or 4th completed `15m` candle in the same `1h` setup window.
11. If the setup reaches the next `1h` window without confirmation, it expires.
12. If `entry_confirmation.require_15m_rsi_reversal` is `true`, after confirmation wait for a completed `5m` entry candle. If it is `false`, skip steps 5-11 and wait for the completed `5m` entry candle directly after the 1h setup.
13. Long entry occurs when:
   - `5m close > 5m middle Bollinger band`
   - `5m close < midpoint(1h lower Bollinger band, 1h middle Bollinger band)`

## Short Setup Chain

1. Use the latest completed `1h` candle.
2. A short setup exists when:
   - `1h close > 1h upper Bollinger band`
   - `1h RSI14 > overbought`
3. The setup trigger time is the close time of that `1h` candle.
4. The setup expires one hour after trigger time.
5. After trigger time, wait for the first completed `15m` candle inside the new `1h` setup window.
6. Capture that first new-hour completed `15m RSI14` as the baseline RSI.
7. Do not use the previous `1h` window's last `15m` candle as baseline.
8. Wait for a later completed `15m` candle inside the same `1h` setup window.
9. Short confirmation occurs when that later `15m RSI14` is less than the baseline RSI.
10. Confirmation may only use the 2nd, 3rd, or 4th completed `15m` candle in the same `1h` setup window.
11. If the setup reaches the next `1h` window without confirmation, it expires.
12. If `entry_confirmation.require_15m_rsi_reversal` is `true`, after confirmation wait for a completed `5m` entry candle. If it is `false`, skip steps 5-11 and wait for the completed `5m` entry candle directly after the 1h setup.
13. Short entry occurs when:
   - `5m close < 5m middle Bollinger band`
   - `5m close > midpoint(1h middle Bollinger band, 1h upper Bollinger band)`

## Initial Stop

Initial stop percent is configured by:

```yaml
trailing_stop:
  initial_stop_pct: 0.05
  first_step_risk_reduction: 0.5
```

- Long initial stop: `entry_price * (1 - initial_stop_pct)`
- Short initial stop: `entry_price * (1 + initial_stop_pct)`

## Position Sizing

Live sizing uses margin fraction times leverage:

```text
notional = account_equity * margin_fraction * leverage
```

Current live config:

- `margin_fraction = 0.11`
- `leverage = 3`
- notional exposure is about `45%` of account equity.

This means "10%" refers to margin, not notional position size.

## Strategy Add-On Rule

The strategy does not add to an existing strategy position.

If the user manually adds to a position on Hyperliquid, the system manages the merged exchange position size for stop maintenance. That manual add-on is not a strategy add signal.

## Long Trailing Stop Chain

For an open long, evaluate completed `5m` candle data against the current `1h` Bollinger levels.

Candidate stop updates:

1. If `5m close > midpoint(1h lower, 1h middle)`, candidate stop reduces initial risk by `first_step_risk_reduction`: `initial_stop_loss + (entry_price - initial_stop_loss) * first_step_risk_reduction`.
2. If `5m close > 1h middle`, candidate stop is `entry_price`.
3. If `5m high >= midpoint(1h middle, 1h upper)`, persist `trailing_stage = 3` and enter midband-follow mode.
   - On the activation poll, set one stop from the current completed `1h middle`: `max(1h middle, entry_price)`.
   - Persist the refreshed `1h` bucket as `midband_follow_bucket_start`.
   - Do not refresh this midband-follow stop again inside the same `1h` bucket just because the 30-second full poll runs again.
   - In the next `1h` bucket, the first relevant poll may refresh once from that bucket's completed `1h middle`.
   - This may relax the stop versus the prior hour's middle band, but never below entry price.
4. If `5m high > 1h upper`, candidate stop is `5m close`.

Before midband-follow mode, only move the stop upward. In midband-follow mode, allow the middle-band stop to relax no lower than entry price. If multiple candidates apply, use the highest candidate stop.

## Short Trailing Stop Chain

For an open short, evaluate completed `5m` candle data against the current `1h` Bollinger levels.

Candidate stop updates:

1. If `5m close < midpoint(1h upper, 1h middle)`, candidate stop reduces initial risk by `first_step_risk_reduction`: `initial_stop_loss - (initial_stop_loss - entry_price) * first_step_risk_reduction`.
2. If `5m close < 1h middle`, candidate stop is `entry_price`.
3. If `5m low <= midpoint(1h lower, 1h middle)`, persist `trailing_stage = 3` and enter midband-follow mode.
   - On the activation poll, set one stop from the current completed `1h middle`: `min(1h middle, entry_price)`.
   - Persist the refreshed `1h` bucket as `midband_follow_bucket_start`.
   - Do not refresh this midband-follow stop again inside the same `1h` bucket just because the 30-second full poll runs again.
   - In the next `1h` bucket, the first relevant poll may refresh once from that bucket's completed `1h middle`.
   - This may relax the stop versus the prior hour's middle band, but never above entry price.
4. If `5m low < 1h lower`, candidate stop is `5m close`.

Before midband-follow mode, only move the stop downward. In midband-follow mode, allow the middle-band stop to relax no higher than entry price. If multiple candidates apply, use the lowest candidate stop.

## Manual Position Handling

The live system polls Hyperliquid positions and reconciles them with local state.

If the exchange has a position but the local system has no open trade:

- Treat it as a user/manual position.
- Adopt it into trailing-stop management.
- Create a system-owned reduce-only stop if order placement is allowed.

If an existing local trade disappears from the exchange:

- Treat it as user/manual close or exchange close.
- Cancel only the system-owned stop order if one exists.
- Archive the local trade.
- Try to record exchange realized PnL.
- If PnL lookup is unavailable or incomplete, archive with `pnl_source = unknown`.

If the exchange position size or entry price changes:

- Treat it as a manual size change.
- Manage the merged exchange quantity.
- Do not interpret the change as a strategy add signal.

Default boundary: do not cancel or replace user-created manual orders.

## Persistence And Journal

The live runner persists state in SQLite.

Required persistent state:

- open managed trades
- trailing stage for open managed trades
- midband-follow refreshed 1h bucket for open managed trades
- pending setup state
- 15m RSI baseline
- 15m confirmation state
- append-only trade events

The system writes journal events only on state changes, not every poll.

Important event types:

- `setup_created`
- `setup_confirmed_15m`
- `setup_expired`
- `entry_opened`
- `manual_adopted`
- `manual_size_changed`
- `stop_updated`
- `exit_archived`

## Live Safety Gates

Testnet orders require both:

- live config allows testnet orders
- CLI uses `--allow-testnet-orders`

Mainnet must remain locked unless the config and CLI explicitly allow it. Do not weaken this safety boundary.

## Terminal Observability

The terminal runner should print concise human-facing status, not a full indicator dump every poll.

Preferred regular output:

- poll timestamp
- symbol
- current logic-chain state
- the next condition being waited for

Useful state messages include:

- `waiting for 1h setup`
- `1h setup met; waiting for first 15m RSI baseline`
- `baseline captured; waiting for 15m RSI reversal`
- `15m RSI reversed; waiting for 5m entry`
- `15m RSI reversal disabled; waiting for 5m entry`
- `managed position; waiting for trailing-stop update`

Keep transition messages visible:

- setup created
- 15m baseline captured
- 15m RSI reversed
- entry opened
- stop moved
- manual position adopted
- manual size changed
- exit archived

Detailed candle values and indicator values should remain available to backend code and tests, but do not need to be printed every poll for human monitoring.

## Explicit Non-Goals

These are not part of the current live strategy consensus:

- old `bbmr_v3_2` volume/range/band-walking/rsi-flat filters
- old `bbmr_v3_2` take-profit, add-on, soft-fail, or early-fail rules
- backtest report logic as live-trading authority
- AI-generated discretionary signals
- breakout trades
- automatic strategy add-ons
- broad every-poll database snapshots

## When In Doubt

If code, tests, or user instructions appear to conflict with this document:

1. Stop and identify the conflict.
2. Read the source-of-truth files listed above.
3. Ask the user or planning zone to confirm the intended strategy behavior.
4. Do not silently import old `bbmr_v3_2` behavior into this strategy.
