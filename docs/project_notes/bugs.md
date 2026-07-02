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
