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

### 2026-06-30 - Live Pending Setup State Was Lost On Restart
- **Issue**: Live runner could lose pending setup, 15m RSI baseline, and confirmation state when the process restarted before entry.
- **Root Cause**: `LiveRuntime` kept setup state only in memory, while SQLite only stored open managed trades.
- **Solution**: Added a `live_pending_setups` table, restored unexpired setups at runtime startup, and persisted setup create/confirm/expire/entry cleanup transitions.
- **Prevention**: Tests now cover restart recovery before and after 15m confirmation, expired setup cleanup, and entry cleanup.

### 2026-06-30 - Stale Live System Stop Cancel Crashed Reconciliation
- **Issue**: Live runner crashed when a local open managed trade had no matching exchange position and its recorded system stop order was already missing/canceled/filled on Hyperliquid.
- **Root Cause**: `_cancel_system_stop()` let CCXT `OrderNotFound`-style exceptions escape before the local trade could be archived.
- **Solution**: Treat only missing-order/stale-order cancellation errors as benign during system stop cancellation, then continue archiving the local trade as `manual_or_exchange_closed`.
- **Prevention**: Tests now cover stale stop cancellation during direct reconciliation and `_poll_once()` multi-symbol processing.

### 2026-06-30 - Live Poll Missed Stop Maintenance and Required Observability
- **Issue**: Hyperliquid live runner acceptance failed because the poll loop did not call live trailing stop maintenance, strategy config paths were only type-checked, and terminal output lacked required candle/indicator/position fields.
- **Root Cause**: `update_stop()` and observability helpers existed outside the main poll path, and live config validation accepted any trailing strategy YAML.
- **Solution**: Call stop maintenance from `_poll_once()` after reconciliation when a managed trade exists, hard-lock `strategy_config` to the canonical `configs/strategy_bbmr_trailing_stop_v1.yaml`, and print latest 1h/15m/5m times plus RSI/price/position/local state fields each poll.
- **Prevention**: Focused live tests now prove `_poll_once()` triggers stop maintenance, rejects non-canonical strategy config paths, and emits required terminal fields.

### 2026-06-30 - Acceptance Script Checked Credentials Too Late
- **Issue**: The initial acceptance implementation could construct a real Hyperliquid client before checking missing credential environment variables.
- **Root Cause**: Credential detection lived on the instantiated client, whose constructor loads exchange markets.
- **Solution**: Added a module-level `missing_credential_names` check and used it before constructing a real client in CLI and acceptance paths.
- **Prevention**: Acceptance now refuses missing credentials locally before exchange calls; dry-run smoke covers the no-credential path.

### 2026-06-29 - Same-Setup Reentry Reused Old 15m Confirmation
- **Issue**: `bbmr_trailing_stop_v1` could open a second same-setup trade after `initial_stop_5m_close` using the old 15m confirmation.
- **Root Cause**: Setup confirmation state remained true after the first initial-stop exit.
- **Solution**: Reset setup confirmation with a `confirmation_after` boundary equal to the first exit time, while preserving the original baseline RSI.
- **Prevention**: Tests now assert second same-setup entries require `confirm_15m_time > first_initial_stop_exit_time`, fresh 5m entry timing, and no third entry in both independent and shared runners.
