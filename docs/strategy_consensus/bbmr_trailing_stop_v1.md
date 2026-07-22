# BBMR Trailing Stop V1 Strategy Consensus

This document is the shared strategy reference for humans and AI agents.

When any zone discusses `bbmr_trailing_stop_v1`, Hyperliquid live behavior, RSI/Bollinger timing, entry confirmation, trailing stops, manual position handling, or related acceptance criteria, read this file before making recommendations or code changes.

## Source Of Truth

- Active strategy config: `configs/strategy_bbmr_trailing_stop_v1.yaml`
- Active live config: `configs/live_hyperliquid_testnet.yaml`
- Strategy helpers: `src/bbmr/trailing.py`
- Live execution runtime: `src/bbmr/live/trailing_runtime.py`
- Feature builder: `src/bbmr/trailing_features.py`

Live behavior is defined only by the active trailing configuration and this consensus; removed Phase-1A filters are unsupported.

This document defines the strategy model, supported states, and safety invariants. For values and switches that are exposed in YAML, the currently loaded, valid YAML is the runtime authority. The user frequently adjusts YAML by hand, so a YAML value may intentionally differ from an example or previously agreed default in this document.

When a YAML/document mismatch is found:

- preserve and use the valid YAML value;
- report the mismatch clearly rather than silently normalizing it;
- do not automatically edit this document to match YAML;
- update this document only when the user explicitly asks to revise the consensus;
- if YAML is missing, invalid, or fails validation, fail safely according to the config/runtime guard instead of falling back silently to a documented example.

This precedence applies only to config-backed values and switches. YAML cannot weaken non-configurable safety invariants such as mainnet locking, exchange-position close verification, protective-stop ownership, or the boundary against cancelling manual orders.

## Implementation Status At 2026-07-17

The accepted working implementation contains the completed-1h NORMAL/SPECIAL/EXSPECIAL classifier, `40/60` versus `32/68` RSI selection, `3x` versus `2x` entry leverage, and the protective/trailing-stop safety baseline.

Accepted `STRATEGY-10A` provides the completed-1h BandWidth `HIGH_EXPANDING` entry guard with per-bucket terminal/journal observations, the previous-completed-5m high/low production trigger, independently persisted middle-band and RSI-direction shadow observations with MFE/MAE outcomes, EXSPECIAL new-entry blocking, and invalid/missing-slope `2x` entry marking for later SPECIAL management.

Accepted `STRATEGY-10B` adds YAML-driven SPECIAL rolling-middle targets with entry-price boundaries, sticky EXSPECIAL defensive half-band targets, frozen staged trailing updates, restart-safe regime persistence, and shared `strategy`/`manual_adopted` management. The authorized YAML split rejects legacy `near_middle_frac`; current valid values are `special_near_middle_frac: 0.0` and `exspecial_near_middle_frac: 0.5`.

Both strategy batches passed independent Acceptance on 2026-07-14 and are the accepted testnet behavior. Git baseline organization and any commit/push remain separate Maintenance work.

Accepted `STRATEGY-11` supplied the isolated trend-position management lane, three-state YAML mode, and durable counterfactual shadow records. The user-approved `STRATEGY-13` target below supersedes only its trend-entry path: the old momentum, near-middle, completed-5m rebreak, hourly candidate, BandWidth trend veto, and market-entry rules are no longer part of the target strategy. At STRATEGY-13 acceptance, the rollout remained `mode: shadow`; STRATEGY-15 is the later authority for active Trend and takeover modes.

## Current Purpose

The current goal is to run a Hyperliquid testnet live trading system for `bbmr_trailing_stop_v1`, then use live observations to decide later mainnet adjustments.

Backtest results are not the authority for the current strategy because prior validation found data/indicator/timing mismatch against Hyperliquid chart behavior.

This document describes the user-approved target strategy behavior. Code may temporarily lag behind a newly revised capability until Execution and Acceptance complete the corresponding change. A missing capability is implementation work; a different valid YAML value is a runtime override and follows the YAML precedence above.

## Strategy Summary

The strategy uses one mean-reversion setup chain, one optional YAML-gated trend-riding chain, and isolated position-management lanes:

- NORMAL: allow a mean-reversion entry to become a profitable trend-following position through the existing staged trailing-stop chain.
- SPECIAL: allow a stricter, smaller entry, but treat the trade as a middle-band mean-reversion trade and close at the rolling completed-1h middle with an entry-price boundary.
- EXSPECIAL: block new mean-reversion strategy entries; for an already managed mean-reversion or manual-adopted position, stop trailing updates, keep the existing protective stop, and use a sticky defensive half-band exit until the position is closed. Its first directional row may separately create the isolated trend pending order defined below.

BandWidth is an independent mean-reversion pre-entry volatility-expansion guard. It can block a new mean-reversion strategy entry before the middle-band slope reaches SPECIAL or EXSPECIAL. It never disables management of an existing position and never controls the isolated trend pending order.

Trend riding is not a fourth mean-reversion regime. A trend position has a distinct source, entry chain, protective-stop path, and active exit path. It never enters the NORMAL staged stop, SPECIAL rolling-middle target, or EXSPECIAL defensive half-band lane.

## Timeframes

- `1h`: setup timeframe.
- `15m`: RSI reversal confirmation timeframe.
- `5m`: entry and trailing-stop maintenance timeframe.

The system works from completed candles. A 5m loop time represents the close time of the latest completed 5m candle.

Never use a forming `15m` candle for RSI baseline or RSI reversal confirmation.

Slope state, BandWidth state, and rolling 1h exit levels use completed `1h` candles only. Forming-1h values do not drive strategy decisions or displays.

## Indicators

- Bollinger Bands:
  - period: `20`
  - standard deviation multiplier: `2.0`
- RSI:
  - period: `14`
  - method: `wilder`
  - warmup/history bars: `500`
  - NORMAL 1h setup thresholds: oversold `40`, overbought `60`
  - SPECIAL and EXSPECIAL 1h setup thresholds: oversold `32`, overbought `68`
- BandWidth:
  - formula: `(1h upper - 1h lower) / 1h middle`
  - percentile lookback: `120` completed 1h candles, calculated per symbol
  - 1h change: `current_bandwidth / previous_bandwidth - 1`
  - 3h change is recorded for later calibration but does not initially block entries

For live use, RSI must be computed from candles fetched from the same exchange environment whose chart is being matched. Hyperliquid testnet uses Hyperliquid testnet candles; Hyperliquid mainnet uses Hyperliquid mainnet candles.

## Completed-1h Slope State

Signed slope is:

```text
current_1h_middle / middle_3_completed_hours_ago - 1
```

State is symbol-, side-, and completed-candle-local:

| State | Long | Short |
| --- | --- | --- |
| NORMAL | `slope > -0.0009` | `slope < 0.0009` |
| SPECIAL | `-0.0025 < slope <= -0.0009` | `0.0009 <= slope < 0.0025` |
| EXSPECIAL | `slope <= -0.0025` | `slope >= 0.0025` |

The target strategy configuration must expose the corresponding values rather than hardcode them:

```yaml
adverse_slope_take_profit:
  enabled: true
  slope_n: 3
  special_slope_threshold_pct: 0.0009
  exspecial_slope_threshold_pct: 0.0025
  special_near_middle_frac: 0.0
  exspecial_near_middle_frac: 0.5
```

`STRATEGY-10B` explicitly authorizes a one-time active-config schema migration: replace the ambiguous legacy `near_middle_frac: 0.0` with `special_near_middle_frac: 0.0` and `exspecial_near_middle_frac: 0.5`. The old `0.0` value is preserved as the SPECIAL middle-target fraction; the separately confirmed EXSPECIAL half-band value is `0.5`. After this migration, both valid YAML values remain user-editable runtime authorities. Do not hardcode either value, map the old field to both regimes, or silently accept the legacy field.

If slope history is missing, non-finite, or otherwise invalid:

- a new setup uses the strict `32/68` RSI thresholds and `2x` entry leverage;
- if that setup opens, it starts in SPECIAL management;
- an existing position keeps its last valid management regime;
- missing data must never downgrade or clear an active EXSPECIAL defensive mode;
- if an existing position has no last valid state, use SPECIAL management until valid slope data returns.

## BandWidth Entry Guard

BandWidth is evaluated from the latest completed `1h` candle together with the shared side-specific entry risk. Its effective state continues to select the 1h RSI threshold and entry leverage before confirmation; its allow/block result is the final mean-reversion authorization only after the completed-5m production trigger. Initial state labels are:

| State | Definition |
| --- | --- |
| LOW | percentile `<= 20` |
| NORMAL | percentile `> 20` and `< 80` |
| HIGH_EXPANDING | percentile `>= 80` and 1h change `>= 0.10` |
| HIGH_STABLE | percentile `>= 80` and `-0.10 < 1h change < 0.10` |
| HIGH_CONTRACTING | percentile `>= 80` and 1h change `<= -0.10` |

Only `HIGH_EXPANDING` is an active market-state block. It blocks new strategy entries for that symbol regardless of slope state. Missing, non-finite, or insufficient BandWidth history also blocks new strategy entries. These blocks do not alter, close, resize, or stop management of an existing strategy or manual-adopted position.

The backend must record raw BandWidth, 120h percentile, 1h change, 3h change, label, guard result, symbol, and completed-1h bucket for later replay. Record one observation per symbol per newly completed 1h bucket, including buckets where no setup exists. Do not duplicate the backend observation on every 30-second poll. When a completed-5m production trigger reaches final authorization and is blocked, also record setup identity, side, completed-5m bucket/close, linkage, source bucket, age, and the BandWidth block reason. `%B` is not used.

The terminal must print one clear BandWidth state line per symbol when the runner first observes the latest completed-1h bucket and once for each new completed-1h bucket thereafter. The line must include the bucket, raw value, percentile, 1h change, 3h change, state label, and `ALLOW` or `BLOCK`. Missing or invalid data must print `UNAVAILABLE`, `BLOCK`, and a concise reason. Do not repeat the same state line on every 30-second poll.

The target strategy configuration must keep the initial filter values user-editable:

```yaml
bandwidth_entry_guard:
  enabled: true
  percentile_lookback: 120
  high_percentile: 80
  min_1h_expansion_pct: 0.10
```

### BandWidth-Slope Entry-Risk Linkage

BandWidth and slow slope use one completed-1h entry-risk decision. The values have distinct units: raw BandWidth and 1h/3h changes are decimal ratios internally and percent for human output; percentile is a `0..100` rank.

- A rapid expansion (`change_1h >= min_1h_expansion_pct`) with close above the upper band is an UP `BW_SHOCK_BLOCK` for adverse short entries; below the lower band is a DOWN block for adverse long entries. This applies even at low percentile rank. Expansion inside the bands has no direction.
- If the canonical `slope_n=3` state is still NORMAL, a matching shock exactly one or two completed buckets ago becomes `BW_CONTINUATION_SPECIAL` only while every finite, non-zero middle-band increment remains strictly in the shock direction. It selects strict `32/68` 1h RSI and `2x` for new strategy entries.
- A current shock blocks rather than becoming continuation. Equality, reversal, invalid data, the opposite side, or age three cancels continuation. Slow SPECIAL, EXSPECIAL, and missing-slope strict fallback remain authoritative when stricter.
- This linkage is entry-only. It does not create a fast slope classifier, persist state, or change open-position management regimes, stops, targets, sizing, or manual-position handling.

## Optional Trend-Riding Decision Chain

### STRATEGY-16 Authoritative Local Watch And Takeover Override

The active YAML authority is `trend_riding.mode: live`, `opposite_mr_takeover_mode: live`, and `pending_ttl_hours: 6`; legacy/missing modes default to `off`. Takeover `live` requires parent `live`; takeover `shadow` requires parent `shadow` or `live`. The active testnet account cap is `execution.max_total_notional_fraction: 1.20`; `exchange.env` remains testnet and `allow_mainnet` remains false.

A pending created from signal bucket `t` expires at `t + 7h`: the first row is observable at `t + 1h`, then receives six completed hours of validity. It is a durable local watch at creation, not an exchange GTC order. Before a touch, long must retain directional slope `>= special_slope_threshold_pct`; short must retain directional slope `<= -special_slope_threshold_pct`. Equality remains directional SPECIAL. Missing, non-finite, or invalid slope cancel fail closed. A completed-1h close at or through that same row's middle cancels: long `close <= middle`, short `close >= middle`. These checks use completed rows only. After terminal expiry cancellation and reservation release only, the expiry candle may create a new ID/F/L/TTL when it independently satisfies the full same-direction EXSPECIAL signal; ambiguous cancellation never renews.

For an opposite protected `source=strategy` MR, Trend persists a waiting reservation but submits no opposite order while the MR is nonzero. `manual_adopted`, manual-size-changed, same-direction, unknown/manual, unprotected, intent, or recovery states are fail-closed. While waiting, directional-NORMAL and completed-1h middle invalidation apply before any fresh L2 touch. A live takeover uses a fresh valid L2 quote with middle invalidation first (`long ask <= middle`, `short bid >= middle`) and L touch second (`long ask <= L`, `short bid >= L`), plus existing spread validation. It persists takeover intent before the first reduce-only MR close. Each fresh remaining quantity causes one new reduce-only close on the next active poll without a renewed touch; ambiguous results wait for fresh truth. Once close/cleanup has started, later entry invalidation is latched and the safety convergence continues to confirmed flat and owned-stop cleanup; it then remains flat and never submits Trend.

Trend leverage/order calls remain zero in the signal-creation cycle and until a later fresh L2 L touch. A fresh invalid or wide quote waits without inference or submission. At a valid touch, live checks middle invalidation first and then submits at most one exact-L GTC after the existing account/ownership/margin/notional gates. No chase, price refresh, or second order is allowed. For takeover, calls remain zero until the entire symbol is confirmed flat and the stored system-owned MR stop is terminal or missing. The MR stop remains until flat. Flat cleanup archives the original MR ID/source with `trend_takeover`; the later Trend trade is a separate `source=trend_riding` row. A pre-fill completed-1h bucket is recorded on the Trend trade so only the first later completed bucket may apply slope exits; protection starts immediately.

MR and Trend use the same reservations: validated gross exchange notional plus non-terminal MR intents, live Trend pending/takeover reservations, and reliable manual non-reduce-only open orders must be `<= equity * 1.20`. Unknown account/order truth blocks new entries but never blocks existing close, cleanup, or protection actions. Every exchange mutation requires a fresh account truth refresh before later-symbol creation.

Trend riding is controlled by one YAML mode and three independently editable values:

```yaml
trend_riding:
  mode: live
  opposite_mr_takeover_mode: live
  pending_ttl_hours: 6
  entry_pullback_pct: 0.01
  weakening_slope_threshold_pct: 0.0018
  initial_stop_distance_pct: 0.05
```

Trend entry reuses `adverse_slope_take_profit.slope_n` and `exspecial_slope_threshold_pct`; trend management also reuses `special_slope_threshold_pct` as its canonical NORMAL floor. Do not duplicate these authorities under `trend_riding`.

The strategy config schema default is `off`; the active YAML is approved testnet-only `live/live`. Valid parent modes are:

| Mode | New trend behavior | Existing behavior |
| --- | --- | --- |
| `off` | Do not create a new trend pending order, simulated position, or real trend position | Mean-reversion entries remain exactly on the accepted path |
| `shadow` | Persist a virtual fixed-price pending order and simulate its lifecycle | Never block, cancel, replace, or reorder a real mean-reversion decision; never call an exchange mutation |
| `live` | Persist a local fixed-price watch, then place one exact-L exchange GTC only after a later valid fresh L2 touch and generic safety checks | Mean-reversion keeps its own canonical slope and BandWidth guards; the trend lane adds no separate MR veto |

Mode is loaded at runner startup; changing YAML requires a runner restart. An unfilled pending order whose stored mode differs from the new startup mode is canceled and locked for that episode; a shadow pending order is never promoted into a live exchange order. Mode otherwise gates new creation only:

- an already open real trend position keeps reconcile, protective-stop, trailing, and exit management in every mode;
- an already open simulated trend position continues to a terminal simulated outcome in every mode;
- switching from `shadow` to `live` marks the clean no-trend comparison baseline as ending at the switch time, because later actual behavior may contain real trend decisions.

### First Directional EXSPECIAL Transition

Use only completed `1h` rows and the canonical slope definition:

```text
middle_slope = current_1h_middle / middle_slope_n_completed_hours_ago - 1
```

- The first row of a continuous upward EXSPECIAL episode creates a long opportunity when `middle_slope >= exspecial_slope_threshold_pct`.
- The first row of a continuous downward EXSPECIAL episode creates a short opportunity when `middle_slope <= -exspecial_slope_threshold_pct`.
- Freeze that first row's completed close as `F`. The frozen close and derived order price never refresh during the episode.
- One directional EXSPECIAL episode gets at most one attempt. A canceled, filled, or otherwise terminal pending order remains locked until that direction exits EXSPECIAL and a later completed row enters a new directional EXSPECIAL episode.
- A runner that starts after an episode is already in progress does not backfill the missed first-row order. A restart may resume a pending order that was durably created before the restart, but must not reconstruct a new one from later rows.
- Missing, non-finite, zero-denominator, or insufficient slope data creates no order and cancels an existing unfilled pending order fail-closed.
- Close momentum, RSI, an outer-band break, BandWidth, a near-middle zone, and completed-5m rebreaks are not trend-entry gates.

### Frozen-Price Local Watch And Exact-L GTC

Let `p = trend_riding.entry_pullback_pct`:

```text
long limit L  = F * (1 - p)
short limit L = F * (1 + p)
```

- `live` first persists one local watch at `L`; the signal poll makes no leverage or exchange-order call. On a later fresh valid L2 quote, long cancels when `ask <= current completed middle` before it can touch, then touches only when `ask <= L`; short mirrors with `bid >= current completed middle` before `bid >= L`. The one resulting exchange GTC is exactly `L`; it does not use the old trend market-entry path.
- `shadow` creates the same virtual pending order. Only future completed `5m` candles may simulate a fill: long checks `low <= current completed middle` before `low <= L`; short mirrors with `high >= current completed middle` before `high >= L`. The simulated fill price is exactly `L` and uses the local conservative taker-on-touch cost assumption.
- Live exchange fill or partial fill has priority over a later polling-time cancel decision. Cancel any unfilled remainder, adopt the actual filled quantity and average price, and immediately install the trend protective stop. The strategy never adds, reverses, or converts an existing position.
- A shadow touch creates one full simulated fill; shadow mode never implies exchange fill accuracy.

While unfilled, cancel the pending order when any of these occurs:

- directional slope returns to NORMAL: long `< special_slope_threshold_pct`; short `> -special_slope_threshold_pct`;
- completed-1h close reaches or crosses current middle: long `close <= middle`; short `close >= middle`;
- a fresh live L2 quote reaches or crosses current middle before an L touch;
- an exchange position, managed trade, conflicting order, emergency lockout, invalid account state, or invalid required market data makes entry unsafe.

Cancel only the stored system-owned trend order. Never cancel a manual order. Once cancel is terminal, do not refresh or replace the order within the same episode.

### BandWidth And Generic Entry Safety

BandWidth is mean-reversion-only evidence. Neither the base `HIGH_EXPANDING` guard nor the H0/H1/H2 linkage may authorize, veto, cancel, or resize a trend pending order. Shadow records still capture the contemporaneous BandWidth state and MR linkage for later comparison.

A real trend pending order reuses the accepted generic protections that remain relevant to a fixed-price GTC limit: emergency lockout, valid completed indicators, no existing position or conflicting order, positive equity, available margin, account-wide notional cap, leverage submission, exchange order confirmation, fill reconciliation, immediate reduce-only protective stop, recoverable missing-protection state, and zero-position verification before stop cancellation/archive. Market-entry spread and slippage gates do not turn the fixed-price limit into a market order.

### Trend Position Sizing And Source

The live config exposes an independent execution authority:

```yaml
execution:
  trend_riding_leverage: 2
```

Trend riding reuses `execution.margin_fraction = 0.15`, so the target notional is `30%` of account equity. It also reuses `max_total_notional_fraction`. Do not couple trend leverage to `adverse_slope_leverage`, and do not add to an existing position.

A real trend trade is persisted with `source = trend_riding`. Source routing, not the current YAML mode, selects its management lane. A manual-adopted or mean-reversion trade is never silently converted to this source.

### Trend Protective Stop And Active Exit

Trend positions use only completed `1h` closes for strategy-driven stop movement:

- Initial long stop: `entry_price * (1 - initial_stop_distance_pct)`.
- Initial short stop: `entry_price * (1 + initial_stop_distance_pct)`.
- Long high-water candidate: `highest_post_entry_completed_1h_close * (1 - initial_stop_distance_pct)`.
- Short low-water candidate: `lowest_post_entry_completed_1h_close * (1 + initial_stop_distance_pct)`.
- Long stop never moves down; short stop never moves up. A stop may pass entry price and retain profit.
- One-time break-even: after the first post-entry completed `1h close >= that row's upper band` for long, or `<= that row's lower band` for short, entry price becomes a permanent stop candidate. A wick or forming candle does not arm it.

Before replacing a real exchange stop, compare the newly calculated stop with a fresh mark. If a long's new stop is already at or above mark, or a short's is already at or below mark, request an immediate market close instead of placing an already-crossed stop. Keep the old reduce-only stop until the exchange confirms zero position. Failure keeps the old stop, the local trade, a retry path, and a high-severity event.

Define directional strength as `middle_slope` for long and `-middle_slope` for short:

- `strength >= weakening_slope_threshold_pct`: trend qualification remains active; clear an earlier weakening warning.
- `special_slope_threshold_pct <= strength < weakening_slope_threshold_pct`: set a weakening warning. While warned, the first completed `1h` close crossing the same row's middle against the position closes market: long `close < middle`, short `close > middle`. A warning and middle cross on the same completed row closes immediately.
- `strength < special_slope_threshold_pct`: canonical NORMAL fallback; close market on that completed `1h` row without waiting for a middle cross.
- Invalid or missing slope data does not clear state or authorize a close. Keep the existing exchange protective stop and wait for valid completed data.

If an active-exit condition appears on a new completed-1h row, submit that close before attempting a strategy stop replacement for the same row. The existing protective stop remains until zero-position verification. Otherwise update the trend stop and apply the already-crossed mark handling above. An actual exchange protective-stop fill always owns the lifecycle if it occurs first.

Trend positions do not execute the NORMAL staged 5m stop chain, SPECIAL rolling-middle target, EXSPECIAL sticky defensive target, EXSPECIAL trailing freeze, or any fixed take-profit.

### Shadow Comparison Record

`shadow` uses the same EXSPECIAL-transition, frozen-price pending, sizing, stop, weakening, and exit calculations, but it never submits leverage, entry, stop, cancel, or close calls. The actual runner continues the accepted current strategy and therefore forms the contemporaneous "without trend riding" baseline.

Persist one complete simulated trend position per symbol at a time in a dedicated SQLite table. Do not reuse mean-reversion `live_pending_setups` or the short-horizon `live_shadow_triggers` table. The shadow record must preserve:

- EXSPECIAL episode, first-row identity, frozen close, limit price, pending status, and terminal reason;
- entry price assumption, observed equity, quantity, notional, leverage, actual-position/open-order/account-guard evidence, and calculation parameters frozen at entry;
- the contemporaneous actual baseline: exchange position, locally managed trade source/side/quantity/entry/current stop/management state, pending mean-reversion setup and stage, and the actual entry decision or block reason;
- full comparison evidence: raw BandWidth, percentile, 1h/3h changes, state/allow/reason, shock direction, H0/H1/H2 linkage per side, canonical slow slope value/state, effective mean-reversion entry risk, first-EXSPECIAL result, and pending cancel/fill checks;
- initial/current stop, favorable completed-1h water mark, break-even state, weakening state, and last processed 1h/5m buckets;
- MFE/MAE, simulated exit price/time/reason, gross PnL, estimated configured costs, net PnL estimate, and explicit simulated-data provenance;
- event-id/time anchors for joining the same symbol's real trades and journal events during the shadow interval;
- whether the no-trend baseline remained clean for the whole interval.

At simulated close, preserve a baseline-end snapshot and enough IDs/time anchors to recover every overlapping actual trade, its source, close reason, realized PnL, fees, and PnL provenance. Zero actual trades is a valid baseline outcome. Do not copy secrets, raw credentials, or unrelated account data into these snapshots.

Pending-order observations and simulated state transitions are journaled only once per completed bucket or state change, not every poll. A simulated position updates MFE/MAE at most once per completed 5m bucket and stop/exit state at most once per completed 1h bucket. Open simulated positions survive restart and continue to closure even if mode becomes `off` or `live`; they never become real positions. Switching to `live` truncates their clean baseline marker at switch time.

The comparison is a labeled counterfactual signal study, not a claim of exchange fill accuracy or a fully isolated virtual account. Record observed executability and cost assumptions so later analysis can separate all trend signals from the subset that would have passed the observed account and market guards.

### Trend Watch Scheduling

When no real/pending managed state exists, keep the accepted completed-1h idle schedule. A virtual pending order or open simulated trend position requests only the completed-5m-aligned checks needed for shadow touch/MFE/MAE processing, rather than permanent 30-second full polling. Reuse the existing fetched OHLCV frames; the trend evaluator must add no OHLCV request of its own. A live GTC order remains exchange-side while normal lightweight reconciliation continues; real managed positions keep the accepted active-position polling and exchange-side protection behavior.

## Entry Confirmation

- `entry_confirmation.require_15m_rsi_reversal` controls whether the 15m RSI reversal layer is required after a 1h setup.
- Current `configs/strategy_bbmr_trailing_stop_v1.yaml` sets it to `false`, so live entry skips the 15m baseline/reversal gate and waits directly for the completed 5m entry candle after a valid 1h setup.
- When set to `true`, the 15m baseline/reversal rules below apply unchanged.

The production 5m trigger is a completed-candle break of the previous completed 5m candle's adverse-side extreme:

- Long: current completed `5m close > previous completed 5m high`.
- Short: current completed `5m close < previous completed 5m low`.

The existing 1h no-chase boundary remains mandatory. This is an entry confirmation for a 1h mean-reversion setup, not permission to run a standalone breakout strategy.

For a valid 1h setup and any enabled 15m confirmation, the production order is: completed 5m data, previous-extreme break plus the existing 1h no-chase boundary, then the same-poll side-specific BandWidth/linkage allow result and non-EXSPECIAL slow slope, followed by account and order-book guards and protected open. A BandWidth-blocked 5m trigger is evidence only; it cannot be replayed after the guard recovers, so a later order needs a new valid completed-5m trigger.

The following alternatives are shadow-only and cannot place orders or alter real position state:

- completed `5m close` crossing the completed 5m Bollinger middle;
- three completed `5m RSI14` values strictly rising for long or strictly falling for short.

Shadow records must include trigger time, simulated entry price, distance from setup close, distance from the 1h no-chase boundary, and subsequent MFE/MAE. When multiple shadow triggers fire, each result remains independently attributable.

## Long Setup Chain

1. Use the latest completed `1h` candle.
2. A long setup exists when:
   - `1h close < 1h lower Bollinger band`
   - `1h RSI14 < 40` in NORMAL; `< 32` in SPECIAL, EXSPECIAL, or when slope history is unavailable or invalid
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
   - current completed `5m close > previous completed 5m high`
   - `5m close < midpoint(1h lower Bollinger band, 1h middle Bollinger band)`
   - then the same-poll side-specific BandWidth/linkage result allows the entry and slow slope state is not EXSPECIAL

## Short Setup Chain

1. Use the latest completed `1h` candle.
2. A short setup exists when:
   - `1h close > 1h upper Bollinger band`
   - `1h RSI14 > 60` in NORMAL; `> 68` in SPECIAL, EXSPECIAL, or when slope history is unavailable or invalid
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
   - current completed `5m close < previous completed 5m low`
   - `5m close > midpoint(1h middle Bollinger band, 1h upper Bollinger band)`
   - then the same-poll side-specific BandWidth/linkage result allows the entry and slow slope state is not EXSPECIAL

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

- `margin_fraction = 0.15`
- `leverage = 3`
- `max_total_notional_fraction = 1.0`
- normal entry notional exposure is `45%` of account equity.
- SPECIAL and invalid/missing-slope fallback strategy entries use `adverse_slope_leverage = 2`, so notional exposure is `30%` of account equity.
- NORMAL strategy entries use `leverage = 3`, so notional exposure is `45%` of account equity.
- A live trend-riding entry uses independent `trend_riding_leverage = 2`, so notional exposure is `30%` of account equity.
- EXSPECIAL blocks new strategy entries and therefore has no new-entry leverage or notional.
- This tier-based leverage selection applies only to new strategy entries; it does not change leverage on existing strategy or adopted manual positions.

This means "15%" refers to margin, not notional position size.

For the supported Hyperliquid Standard/cross account schema, live `account_equity` is the validated CCXT `USDC.total` (`accountValue`) exactly once; unrealized PnL is not added again. Available margin is `min(valid CCXT USDC.free, valid raw withdrawable)`. Missing, non-finite, or negative account values fail closed before position reconciliation or any order path.

Before a new strategy entry, the live runner blocks the entry if existing exchange notional plus durable reservations plus the proposed strategy notional would exceed `account_equity * max_total_notional_fraction`. Existing notional includes all exchange positions, including manual/adopted positions, using validated `positionValue`/`notional`, or only a validated `qty * mark_price` when the exchange notional is unavailable. Reservations include every non-terminal MR entry intent, every non-terminal live trend pending order, and reliably valued non-system non-reduce-only open orders at remaining quantity times price; shadow records and valid reduce-only orders reserve zero. Missing or invalid quantity, side, ownership, reduce-only flag, remaining amount, price, or other required open-order truth blocks every new strategy entry account-wide without cancelling that order. `contractSize` and entry price are never valuation fallbacks. This cap only blocks new strategy entries; it does not stop management of existing positions.

Before real strategy orders, the live runner also blocks new entries when account equity is non-positive, available margin is below durable reserved margin plus the proposed margin requirement (`proposed_notional / selected_leverage`), the entry-side slope state is EXSPECIAL, or the BandWidth guard is unavailable or `HIGH_EXPANDING`. After an order-state mutation, later symbols use a refreshed balance, position, and account-wide open-order snapshot; refresh failure blocks later entries for that poll. These guards only block new strategy entries and do not affect existing position management, stop updates, take-profit checks, or manual reconcile.

Before a real mean-reversion entry, the live runner checks one Hyperliquid L2 top-of-book snapshot. If best bid or best ask is missing/invalid, or if `(best_ask - best_bid) / ((best_ask + best_bid) / 2)` exceeds `execution.max_market_spread_bps`, the entry is blocked before leverage or order submission. The same snapshot is the top-book-mid journal reference and the one-shot hard IOC limit: long at or below `best_ask * (1 + max_entry_slippage_bps / 10000)`; short at or above `best_bid * (1 - max_entry_slippage_bps / 10000)`. Exchange price precision must remain inside that boundary. The guard does not use CCXT ticker bid/ask or ticker last, refetch L2, chase, or widen the order. After a confirmed fill, a returned fill price (`average` or `price`) outside the reference threshold still records `entry_slippage_exceeded` while the position is protected and managed.

## Strategy Add-On Rule

The strategy does not add to an existing strategy position.

If the user manually adds to a position on Hyperliquid, the system manages the merged exchange position size for stop maintenance. That manual add-on is not a strategy add signal.

## Strategy Entry Lifecycle

For real orders, a local strategy trade with `status = open` means the exchange has confirmed the same symbol/side position and, on the current managed-position poll, has confirmed one persisted system-owned protective stop is open, reduce-only, on the closing side, for the formatted position quantity and current formatted trigger price. A local stop ID alone is not protection. If entry fills or manual adoption occurs before that truth is confirmed, the runner keeps a recoverable unprotected record and blocks every new strategy entry until recovery succeeds.

Stop replacement persists one deterministic client-ID intent before submission. It confirms the replacement stop before cancelling only the previously persisted system stop ID; a missing/ambiguous create or cancel result remains recovery state and is resumed after restart without scanning or cancelling manual orders. `maintain_exchange_stop = true` is required whenever testnet order submission is enabled. Observation, dry-run, and no-order-permission paths never fabricate `open/protected` state.

Mean-reversion entry persists one deterministic client-ID intent before leverage or IOC submission. Its identity is the bound runner account, symbol, side, setup trigger, and completed-5m trigger. The submit-attempt marker is durable before the only IOC call. Missing responses, delayed positions, lookup timeout, malformed order truth, and restart only reconcile that persisted identity and retain its reservation; they never resubmit the same trigger. A same-side actual position, including a partial fill, terminalizes the intent atomically with a recoverable `entry_unprotected` trade before the accepted protective-stop path may promote it to `open`. Confirmed terminal no-fill consumes that completed-5m trigger; only a new valid completed-5m trigger may create a later intent.

## Long Trailing Stop Chain

For an open long in NORMAL or SPECIAL management, evaluate completed `5m` candle data against the current `1h` Bollinger levels. Stop staged updates when sticky EXSPECIAL defensive mode activates, while leaving the last system-owned protective stop on the exchange.

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

For an open short in NORMAL or SPECIAL management, evaluate completed `5m` candle data against the current `1h` Bollinger levels. Stop staged updates when sticky EXSPECIAL defensive mode activates, while leaving the last system-owned protective stop on the exchange.

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

## Position-Management Regime Routing

All system-managed positions, including `strategy` and `manual_adopted`, participate in symbol- and side-local slope-state evaluation. Leverage selection remains strategy-entry-only and never re-leverages an existing position.

| Regime | New mean-reversion strategy entry | Open-position management |
| --- | --- | --- |
| NORMAL | `15%` margin at `3x` after all guards pass | full staged trailing-stop chain; no middle-band TP |
| SPECIAL | `15%` margin at `2x`, strict RSI, after all guards pass | staged protective stop remains active in parallel with rolling middle-band TP |
| EXSPECIAL | blocked | freeze the existing protective stop, stop staged trailing updates, and use sticky rolling half-band defensive exit |
| invalid/missing slope | strict RSI and `2x` if BandWidth and all other guards pass | use SPECIAL management unless a last valid regime already exists |

NORMAL is the only regime intended to let the full position pass the 1h middle and become an upper-band or lower-band trend-following runner. SPECIAL deliberately closes the full position at its middle-band target while SPECIAL remains active.

## SPECIAL Rolling Middle-Band Take Profit

SPECIAL management is a parallel active take-profit path for all system-managed open positions:

- Evaluate at strategy entry and then at most once per new completed `1h` bucket.
- Compute the YAML-driven near-middle level with `special_near_middle_frac` in `[0, 1]`:
  - Long level: `middle - (middle - lower) * special_near_middle_frac`.
  - Short level: `middle + (upper - middle) * special_near_middle_frac`.
- Apply the entry-price boundary after that calculation: long target is `max(long level, entry_price)` and short target is `min(short level, entry_price)`.
- With the authorized current YAML value `special_near_middle_frac = 0.0`, the near-middle level is the completed-1h middle.
- The entry-price boundary keeps SPECIAL as a profit or breakeven exit; it does not intentionally realize a loss through this target.
- Each managed-position poll checks live market price against the active target.
- Long closes when live price is `>= target`; short closes when live price is `<= target`.
- The existing protective and staged stop chain continues while waiting. Whichever exit occurs first owns the close lifecycle.
- If a later valid completed-1h slope state returns to NORMAL before the target triggers, clear the SPECIAL target and return fully to NORMAL trailing management.
- If the state escalates to EXSPECIAL, replace SPECIAL management with EXSPECIAL defensive mode.

Because SPECIAL uses a hard full-position middle-band target, a position that reaches that target while still SPECIAL does not continue to the outer-band trend-running stages.

## EXSPECIAL Defensive Exit

EXSPECIAL is a risk-off management mode, not an ordinary take-profit state:

- Block every new mean-reversion strategy entry in EXSPECIAL. A qualifying mean-reversion setup may still be journaled for analysis, but it cannot submit an order. The isolated trend lane follows its own first-EXSPECIAL pending-order rule.
- Existing `strategy` and `manual_adopted` positions enter EXSPECIAL defensive mode.
- On activation, preserve the current system-owned reduce-only protective stop and stop all later staged trailing-stop updates.
- Never cancel, loosen, or remove the protective stop merely because EXSPECIAL is active. It remains the exchange-side failure backstop until the position is confirmed closed.
- Use a rolling completed-1h defensive target with no entry-price floor, calculated from YAML `exspecial_near_middle_frac` in `[0, 1]`:
  - Long: `middle - (middle - lower) * exspecial_near_middle_frac`.
  - Short: `middle + (upper - middle) * exspecial_near_middle_frac`.
  - With the authorized current YAML value `exspecial_near_middle_frac = 0.5`, these are the lower/middle and middle/upper half-band targets.
- Refresh the defensive target at most once per new completed `1h` bucket.
- Each managed-position poll checks live price. Long closes at or above the target; short closes at or below the target.
- The target may intentionally close at a loss because its purpose is to exit a severely adverse regime before the original protective stop is reached.
- EXSPECIAL is sticky for the life of that managed position. A later slope downgrade does not resume normal trailing or clear the defensive target.

If the defensive market close is submitted, the runner must confirm the same symbol/side exchange position is zero before cancelling the system-owned stop and archiving the trade. A close, quote, or verification failure keeps the local trade open and the protective stop intact for a later retry.

## Manual Position Handling

The live system polls Hyperliquid positions and reconciles them with local state.

If the exchange has a position but the local system has no open trade:

- If `execution.adopt_manual_positions` is `true`, treat it as a user/manual position, adopt it into trailing-stop management, and create a system-owned reduce-only stop if order placement is allowed.
- If `execution.adopt_manual_positions` is `false`, do not create a local trade or system stop; print a clear waiting message.

If an existing local trade disappears from the exchange:

- Treat it as user/manual close or exchange close.
- Cancel only the system-owned stop order if one exists.
- Archive the local trade.
- Try to record exchange realized PnL.
- If PnL lookup is unavailable or incomplete, archive with `pnl_source = unknown`. Exact exchange PnL is recorded only when the runner has a successful owned close order/client identity and matching fill quantity; same-symbol opposite-side history is never an attribution fallback.

If the exchange position size or entry price changes:

- If `execution.manage_full_manual_added_size` is `true`, treat it as a manual size change and manage the merged exchange quantity.
- If `execution.manage_full_manual_added_size` is `false`, do not replace the system stop for the changed size; mark protection recovery rather than claiming the old-quantity stop protects the full exchange position.
- Do not interpret a manual size change as a strategy add signal.

Default boundary: do not cancel or replace user-created manual orders.

## Persistence And Journal

The live runner persists state in SQLite.

Required persistent state:

- open managed trades
- trailing stage for open managed trades
- midband-follow refreshed 1h bucket for open managed trades
- last valid slope regime for open managed trades
- SPECIAL TP active state, completed-1h bucket, and target price
- EXSPECIAL sticky defensive-mode state, completed-1h bucket, and target price
- whether staged trailing updates are frozen by EXSPECIAL
- pending setup state
- non-terminal MR entry intent identity, approved L2/IOC boundary, submit attempt, reservation, and reconciliation result
- 15m RSI baseline
- 15m confirmation state
- BandWidth entry-guard decision evidence
- shadow 5m trigger observations and independently attributable outcomes
- append-only trade events
- current trend EXSPECIAL episode lock and pending-order identity, including `F`, `L`, side, mode, order ID, status, fill/cancel evidence, and terminal reason
- real trend-position source plus high/low-water stop state, break-even state, weakening state, and last processed completed-1h bucket
- complete open and closed trend-shadow trades, including frozen pending/entry evidence, stop/exit state, MFE/MAE, simulated PnL provenance, and baseline anchors

The system writes journal events only on state changes, not every poll.

Runner ownership is bound before any SQLite migration, dashboard write, client construction, reconciliation, or journal write. Canonical configured and CLI symbols are unique base symbols (`BTC`, not parallel `btc`/`BTCUSDC` aliases). The runner derives an irreversible fingerprint from the configured environment and normalized public wallet address; SQLite and lock files store only that fingerprint plus environment, never the raw wallet or private key. It acquires the wallet-identity lock before the existing database-local liveness lock.

`--dry-run` derives a deterministic isolated simulation storage and lock namespace before any lock, store, lifecycle, dashboard, client, or runtime construction. Its state persists across simulated restarts but never shares production SQLite, dashboard, database-local lock, or wallet-identity paths. A recognized pending-setup candle transport failure retains the setup and records bounded WARN evidence; malformed or unexpected validation failures propagate to the fatal boundary. After a store opens, an unhandled fatal records sanitized CRITICAL evidence and lifecycle `error`, then rethrows.

The read-only dashboard serializes the runner's actual per-symbol branch trace. It does not reconstruct setup, completed-5m trigger, BandWidth, or account/orderbook decisions. Its overview API defaults to the first runner-provided configured symbol, and the frontend renders only that backend list.

A new empty SQLite store binds automatically. A non-empty legacy store requires the explicit one-time `--bind-legacy-identity` authorization and only when it has no active managed trade or non-terminal trend pending order; a bound store never rebinds. Active managed trades have a database-enforced unique `exchange_position_key`. Lifecycle creation, recovery-to-open, stop state changes, manual adoption/size changes, and archive state are committed with their matching journal event in one local SQLite transaction. Exchange calls remain outside those transactions.

Important event types:

- `setup_created`
- `setup_confirmed_15m`
- `setup_expired`
- `entry_opened`
- `manual_adopted`
- `manual_size_changed`
- `stop_updated`
- `bandwidth_entry_blocked`
- `bandwidth_state_observed`
- `special_tp_activated`
- `special_tp_cleared`
- `exspecial_defensive_mode_activated`
- `shadow_entry_triggered`
- `trend_pending_created`
- `trend_pending_canceled`
- `trend_pending_filled`
- `trend_shadow_pending_created`
- `trend_shadow_pending_canceled`
- `trend_shadow_pending_filled`
- `trend_shadow_opened`
- `trend_shadow_stop_updated`
- `trend_shadow_weakening_started`
- `trend_shadow_weakening_cleared`
- `trend_shadow_closed`
- `trend_shadow_baseline_truncated`
- `trend_entry_opened`
- `trend_stop_updated`
- `trend_weakening_started`
- `trend_weakening_cleared`
- `trend_exit_triggered`
- `exit_archived`

## Live Safety Gates

Testnet orders require both:

- live config allows testnet orders
- CLI uses `--allow-testnet-orders`

Mainnet must remain locked unless the config and CLI explicitly allow it. Do not weaken this safety boundary.

## Terminal Observability

The terminal runner should print concise human-facing status, not a full indicator dump every poll. BandWidth is the exception at the completed-1h boundary because it is not directly visible on the Hyperliquid page: print its full state once per symbol per newly observed completed-1h bucket, not once per 30-second poll.

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
- `15m RSI reversal disabled; waiting for previous 5m high/low break`
- `BandWidth HIGH_EXPANDING; strategy entry blocked`
- `BTC BandWidth bucket=... value=... percentile=... change_1h=... change_3h=... state=HIGH_EXPANDING guard=BLOCK`
- `NORMAL managed position; waiting for trailing-stop update`
- `SPECIAL managed position; waiting for rolling 1h middle TP or protective stop`
- `EXSPECIAL managed position; trailing updates frozen; waiting for defensive half-band exit or protective stop`
- `TREND SIGNAL ... F=... L=... middle=... expires=... phase=...` exactly once when a local watch is created
- `TREND ... local pending ... F=... L=... middle=... expires=... phase=...` while waiting
- `TREND TOUCH ...` and `TREND ORDER ...` only after a live touch reaches submission
- `TREND INVALIDATED/CANCEL ...` for directional-NORMAL, completed-1h-middle, live-middle, TTL, or safety terminalization
- `TREND SHADOW position; simulating completed-candle stop and exit chain`
- `TREND managed position; waiting for completed-1h stop or weakening exit`

Keep transition messages visible:

- setup created
- 15m baseline captured
- 15m RSI reversed
- entry opened
- stop moved
- manual position adopted
- manual size changed
- BandWidth entry blocked
- SPECIAL TP activated or cleared
- EXSPECIAL defensive mode activated
- shadow entry trigger recorded
- trend pending order created, canceled, filled, or partially filled
- trend shadow position opened, stop moved, weakened, recovered, or closed
- real trend position opened, stop moved, weakened, recovered, or closed
- exit archived

Detailed candle values and indicator values should remain available to backend code and tests, but do not need to be printed every poll for human monitoring.

## Explicit Non-Goals

These are not part of the current live strategy consensus:

- removed Phase-1A volume/range/band-walking/rsi-flat filters; the narrow completed-1h BandWidth `HIGH_EXPANDING` entry guard defined in this document is the only active BandWidth filter
- removed Phase-1A take-profit, add-on, soft-fail, or early-fail rules
- backtest report logic as live-trading authority
- AI-generated discretionary signals
- standalone breakout trades; a previous completed 5m high/low break remains only a mean-reversion setup confirmation and is not a trend-entry trigger
- market entry for a new trend ride; the trend lane uses the frozen-price GTC limit defined above
- automatic strategy add-ons
- broad every-poll database snapshots
- `%B`
- BandWidth-based forced exits or changes to existing-position leverage
- BandWidth authorization or veto of a trend pending order; BandWidth remains recorded only as contemporaneous mean-reversion evidence
- using the browser to change trend mode, place orders, control the runner, or write SQLite
- treating simulated trend PnL as exchange-realized PnL or a fill-accurate independent-account backtest

## When In Doubt

If code, tests, or user instructions appear to conflict with this document:

1. Stop and identify the conflict.
2. Read the source-of-truth files listed above.
3. For a config-backed value, use the currently loaded valid YAML and report the mismatch without automatically changing this document.
4. For a capability, state transition, or safety-invariant conflict, ask the user or planning zone to confirm the intended strategy behavior.
5. Do not reintroduce removed Phase-1A behavior into this strategy.
