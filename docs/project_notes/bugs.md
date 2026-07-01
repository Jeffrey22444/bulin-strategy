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
