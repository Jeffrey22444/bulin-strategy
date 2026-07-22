# Bug Log

Track recurring or instructive bugs here. Keep entries brief and chronological.

## Entry Format

```markdown
### YYYY-MM-DD - Brief Bug Description
- **Issue**: What went wrong
- **Root Cause**: Why it happened
- **Solution**: How it was fixed
- **Prevention**: How to avoid it next time
```

## Entries

### 2026-07-20 - Closed Protection History Blocked New Strategy Entries
- **Issue**: Archived trades retaining `protection_status='unknown'` or `'recovery'` incorrectly triggered the account-wide protective-stop recovery gate.
- **Root Cause**: The recovery query considered protection status without excluding the known terminal `status='closed'`, although archival correctly preserves that historical field.
- **Solution**: Exclude only `closed` trades before evaluating unsafe protection states; keep every non-closed unsafe state and every stop-replacement intent blocking.
- **Prevention**: Temporary SQLite and runtime-seam tests cover closed history, active unsafe states, and pending stop replacements.

### 2026-07-20 - Frontend Rejected Valid Entry Flow After Backend Reordered Checks
- **Issue**: The localhost dashboard displayed only its unavailable fallback despite fresh snapshot and API data.
- **Root Cause**: The frontend required entry steps and connectors to arrive in its visual order. The backend correctly returned the same known nodes in its evaluation order, with BandWidth before the completed-5m nodes, so the frontend discarded the complete payload.
- **Solution**: Validate the known entry node and connector sets, including valid states and uniqueness, without treating transport order as a schema requirement; keep management-lane ordered validation unchanged.
- **Prevention**: Frontend test asserts the order-tolerant entry validation helpers; Chrome verification confirms a fresh live payload renders after reload.

### 2026-07-13 - Special TP market-price timeout could still crash live runner
- **Issue**: A recoverable timeout from `get_market_price()` while an adverse-slope TP state was active could exit the live runner.
- **Root Cause**: The managed-position TP price read in `_poll_once()` was outside the existing startup, poll-read, and entry-check network guards.
- **Solution**: Catch only recoverable errors around that price read, append a symbol-level WARN journal event, skip the TP check, then continue normal trailing-stop maintenance.
- **Prevention**: Focused live-run tests cover recoverable price-read continuation and unknown-error propagation.

### 2026-07-13 - Entry-side open-order probe timeout could still crash live runner
- **Issue**: The live runner could still exit on Hyperliquid testnet `RequestTimeout` during `fetch_open_orders()` even after startup and poll-read network guards were added.
- **Root Cause**: `run.py` only treated startup client creation and the initial `_poll_once()` read bundle as recoverable. Later entry-side exchange reads inside `maybe_open_strategy_trade()` could still call `fetch_open_orders()` and bubble a recoverable timeout out of the live loop.
- **Solution**: Catch recoverable network errors around `maybe_open_strategy_trade()` in `_poll_once()`, append a WARN journal event for that symbol, print an entry-check warning, and skip entry work until the next cycle.
- **Prevention**: Focused live-run tests cover `RequestTimeout` during entry-side open-order probing.

### 2026-07-09 - Live runner exited on startup market-load timeout
- **Issue**: Hyperliquid testnet startup could crash before entering the live loop when `load_markets()` timed out.
- **Root Cause**: The recoverable network guard only wrapped `_poll_once()` reads; `HyperliquidClient(config)` in `main()` performs `exchange.load_markets()` earlier, so `RequestTimeout` escaped before the loop started.
- **Solution**: Treat recoverable startup `HyperliquidClient` construction failures like poll-time network errors: append a WARN journal event, print a startup warning, and retry on the next cycle; `--once` exits cleanly after logging the warning.
- **Prevention**: Focused live-run tests cover recoverable startup `RequestTimeout` and unknown startup exception propagation.

### 2026-07-08 - Strategy entry could mark local open before exchange protection was confirmed
- **Issue**: The live strategy entry path created a local `status=open` trade before real `set_leverage`, market entry, and protective stop creation were all confirmed.
- **Root Cause**: `maybe_open_strategy_trade()` wrote the local trade before the exchange lifecycle completed, so later exchange failures could leave misleading local state or duplicate-entry risk.
- **Solution**: For real orders, create `open` only after same symbol/side position confirmation and successful protective stop creation; filled entries with stop failure are stored as `entry_unprotected` and repaired by later reconcile.
- **Prevention**: Focused tests cover leverage failure, market-entry failure, missing position confirmation, stop failure after fill, store persistence for `entry_unprotected`, and reconcile promotion to `open`.

### 2026-07-14 - Dashboard Must Not Present Unprotected Entry As Managed Position
- **Cause**: The dashboard observation treated every locally managed trade as protected, including persisted `entry_unprotected` recovery records.
- **Solution**: Expose `entry_unprotected` as an explicit blocked/tagged state, mute its management branch, and freeze archive SVG state directly from the closing trade rather than a prior dashboard snapshot.
- **Prevention**: Dashboard tests cover unprotected display/branch state and reject stale `current.json` content in newly created archive SVGs; frontend tests assert branch connectors are rendered from backend data.

### 2026-07-08 - Adverse-slope TP archived before exchange position zero confirmation
- **Issue**: The adverse-slope take-profit path could cancel the system stop and archive the local trade immediately after submitting a reduce-only market close.
- **Root Cause**: `maybe_close_adverse_slope_take_profit()` treated close-order submission as final instead of confirming the same symbol/side exchange position was gone.
- **Solution**: Fetch positions after close submission; archive only when the same symbol/side position is absent or zero, otherwise update local quantity and replace the protective stop for the remaining position.
- **Prevention**: Focused live-runtime tests cover confirmed-zero archive, same-symbol/opposite-side isolation, residual same-side quantity protection, and close/fetch failure paths that keep the trade open.

### 2026-07-08 - Protective stop replacement could leave an unprotected position
- **Issue**: Replacing a managed protective stop could cancel the old system stop before the new reduce-only stop was created and could store `"None"` when the exchange response lacked an order id.
- **Root Cause**: `_replace_stop()` performed cancel-then-create and used `str(order.get("id"))` without validating the returned id.
- **Solution**: Create and validate the new reduce-only stop id before cancelling the old stop; on create failure or missing id, append `protective_stop_failed`, keep the prior local stop state, and block later strategy entries through a runtime emergency flag.
- **Prevention**: Focused live-runtime tests cover stop-create failure, missing id, old-stop preservation, no `"None"` id writes, and strategy-entry blocking after a protective stop failure.

### 2026-07-01 - Live runner exited on transient exchange read timeout
- **Issue**: Hyperliquid testnet read timeouts or short network failures from balance, positions, or candle fetches could bubble out of the live loop and stop the runner.
- **Root Cause**: `_poll_once()` exchange reads were called without a live-loop boundary for recoverable timeout exceptions.
- **Solution**: Catch known read timeout and network-connectivity exceptions around the read-only poll phase, print one concise Beijing-time network-error line, and continue to the next cycle while re-raising unknown exceptions.
- **Prevention**: Focused live-run tests cover timeout during `fetch_balance`, ccxt `NetworkError`, feature-fetch timeout before state changes, plus unknown exception propagation.

### 2026-07-01 - Live runner crashed on tz-naive/tz-aware completed-candle comparisons
- **Issue**: After live terminal output was reduced, completed-candle checks could compare UTC-aware OHLCV indexes against tz-naive runtime timestamps and crash.
- **Root Cause**: `HyperliquidClient.now()` returned naive local datetimes, while exchange OHLCV indexes were UTC-aware; `latest_completed_row()` did not normalize either side before comparison.
- **Solution**: Normalize completed-candle helper inputs to UTC-aware timestamps, return UTC-aware client `now()`, and convert only terminal display timestamps to Asia/Shanghai.
- **Prevention**: Focused live tests cover naive-clock/aware-candle comparisons, Beijing terminal output, and avoiding duplicate per-symbol position fetches.

### 2026-07-01 - Live trailing strategy used stale/forming data around entry
- **Issue**: `bbmr_trailing_stop_v1` live path could use the previous 1h window's last 15m RSI as baseline, act on a forming 5m candle, keep estimated entry stop after an exchange average fill, or strategy-open while an exchange position/order already existed.
- **Root Cause**: The shared trailing helper captured 15m baseline at setup creation using `trigger_time`, while live runtime used the last 5m row directly and lacked final exchange position/open-order guards before strategy entry.
- **Solution**: Let setup persist before baseline, capture the first completed 15m candle inside the new setup window, use only latest completed 5m rows for entry/stop, update entry/initial/current stop from order `average`/`price`, and add minimal exchange position/open-order entry guards.
- **Prevention**: Focused live tests now cover new-window baseline, forming 5m entry/stop rejection, fill-average stop update, and exchange position/open-order entry blocking.

### 2026-07-01 - Hyperliquid market orders crashed with `price=None`
- **Issue**: Testnet live run crashed when trying to open a market position on Hyperliquid through ccxt.
- **Root Cause**: `create_market_entry()` and `close_position_market()` submitted Hyperliquid `market` orders with `price=None`, but ccxt Hyperliquid requires a reference price to calculate slippage bounds.
- **Solution**: Reuse `HyperliquidClient.get_market_price()` and pass the current market price into both market-order code paths.
- **Prevention**: Keep a focused client regression test asserting Hyperliquid market orders carry a concrete price instead of `None`.
