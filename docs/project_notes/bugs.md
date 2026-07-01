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

### 2026-07-01 - Hyperliquid market orders crashed with `price=None`
- **Issue**: Testnet live run crashed when trying to open a market position on Hyperliquid through ccxt.
- **Root Cause**: `create_market_entry()` and `close_position_market()` submitted Hyperliquid `market` orders with `price=None`, but ccxt Hyperliquid requires a reference price to calculate slippage bounds.
- **Solution**: Reuse `HyperliquidClient.get_market_price()` and pass the current market price into both market-order code paths.
- **Prevention**: Keep a focused client regression test asserting Hyperliquid market orders carry a concrete price instead of `None`.
