# Architectural Decisions

Track durable project decisions here. Use concise ADRs and keep historical context.

## Entry Format

```markdown
### ADR-001: Decision Title (YYYY-MM-DD)

**Context:**
- Why the decision was needed

**Decision:**
- What was chosen

**Alternatives Considered:**
- Option -> Why rejected

**Consequences:**
- Benefits and trade-offs
```

## Decisions

### ADR-015: Local Trend Watch With Middle-First Invalidation (2026-07-22)

**Context:** A Trend GTC submitted at signal creation could sit through a directional-NORMAL recovery or a completed-1h return through the middle. A pullback quote can also cross the middle and L in the same observation.

**Decision:** Persist first-EXSPECIAL Trend as a local F/L/TTL reservation. Do not submit leverage or GTC in the creation cycle. Before any live L touch, cancel on directional NORMAL using the canonical SPECIAL threshold or a completed-1h close through current middle. On fresh valid L2, check middle invalidation before exact-L touch. Shadow mirrors this ordering with future completed-5m low/high and a taker-on-touch assumption. A waiting opposite-MR takeover uses the same checks; a started close/cleanup latches later invalidation and finishes the protected flat/owned-stop cleanup, then remains flat without Trend entry.

**Consequences:** No YAML, database-schema, or order-price formula changes are needed. Existing F/L identity, TTL-only renewal, reservations, fill-wins recovery, and zero-position-before-owned-stop-cleanup ordering remain authoritative. Terminal output exposes SIGNAL, local F/L/middle/expiry/phase, TOUCH, ORDER, and INVALIDATED/CANCEL transitions.

### ADR-014: Local-Controlled Trend Takeover And Six-Hour Pending Validity (2026-07-21)

**Context:** A Hyperliquid symbol is one-way netted, so an opposite Trend order cannot coexist safely with a protected strategy MR. The previous pending cancellation tied validity to EXSPECIAL continuity and rolling-middle price movement, which rejects intended pullbacks.

**Decision:** Trend pending validity uses a six-hour completed-candle TTL, signed-slope reversal only, and terminal-first renewal. For an eligible protected opposite `source=strategy` MR, the local state machine persists a waiting reservation, then on a fresh L2 touch closes the MR reduce-only to confirmed full-symbol flat, confirms cleanup of only its system-owned stop, archives the original MR as `trend_takeover`, and only then revalidates and submits the existing fixed-L GTC. Partial MR closes remain actively latched: every fresh remainder receives one new reduce-only close on the next active poll. `manual_adopted`, manual-size-changed, same-side, unknown, intent, and recovery ownership stay blocked. Both parent and takeover modes are active `live` in the approved testnet YAML; the account cap is `1.20`.

**Consequences:** ADR-008's frozen F/L and isolated Trend management remain; its conflicting pending-cancel and direct-conflict behavior is superseded. No runner restart is authorized by this decision. A future Maintenance task alone may prove a running process loaded the YAML.

### ADR-013: Operational Simulation, Cleanup, And Dashboard Truth (2026-07-20)

**Decision:**
- Keep dry-run state in a deterministic isolated storage and lock namespace. Preserve pending setups only for recognized transport failures; record sanitized fatal lifecycle evidence after store open and rethrow the original failure.
- Testnet acceptance cancels only its known owned stop after strict zero confirmation. Exchange PnL is exact only for a known close identity with exact attributable quantity; otherwise it is unknown.
- The dashboard renders runner-owned decision traces and backend-provided configured symbols instead of re-evaluating strategy conditions.

**Consequences:**
- This is the Execution implementation gate only. Root `.env` permissions, dependency lock, and `frontend/.git` remain a separate Maintenance phase.

### ADR-012: Durable MR Entry Intent And Account Reservation (2026-07-20)

**Context:**
- An IOC response can be lost while the exchange later exposes a fill or terminal order, and a multi-symbol poll can otherwise use stale account facts after an earlier submission.

**Decision:**
- Persist one MR intent keyed by bound account, symbol, side, setup trigger, and completed-5m trigger. Persist its deterministic Hyperliquid client ID and submit-attempt marker before the only IOC submission; unknown results reconcile only and never resubmit that trigger.
- New-entry budgets combine validated exchange positions with non-terminal MR intents, non-terminal live trend pending orders, and strictly valued non-system non-reduce-only open orders. Unknown manual-order truth blocks entries without cancellation. Refresh account truth after an order-state mutation; a refresh failure blocks later entries for that poll.

**Consequences:**
- Confirmed fills move intent ownership atomically into the existing unprotected-to-protected stop path, while confirmed no-fill consumes its 5m trigger. Shadow records and valid reduce-only orders reserve zero; existing position management remains available when entry truth is blocked.

### ADR-011: Verified Stop Truth And Durable Replacement (2026-07-20)

**Context:**
- A local stop ID or successful create response does not prove that an exchange-side protective order is live, correctly scoped, or safe to replace after an interrupted request.

**Decision:**
- Treat a managed trade as protected only after the pinned CCXT order response verifies persisted ownership, open status, symbol, closing side, reduce-only flag, formatted quantity, and formatted trigger. Persist a deterministic-client-ID replacement intent before submission; confirm the new stop before cancelling only the old persisted system ID, and retain recovery on any unknown result.

**Consequences:**
- Recovery blocks new strategy entries account-wide and resumes across restart. Order-capable testnet configuration requires exchange-stop maintenance; observation paths cannot claim a protected trade. Manual orders are neither scanned nor cancelled.

### ADR-010: Runtime Identity And Atomic Lifecycle Evidence (2026-07-20)

**Context:**
- A SQLite path and implicit `default` position key do not establish wallet/environment ownership, and separate state/event commits can leave lifecycle evidence incomplete.

**Decision:**
- Canonical unique symbols and an irreversible environment-plus-normalized-public-wallet fingerprint define runner ownership. Acquire its independent identity lock before the existing database-local liveness lock; store only fingerprint and environment. Empty stores bind automatically, while a non-empty legacy store requires `--bind-legacy-identity` and no active trade or non-terminal trend pending order. Binding is permanent.
- Enforce one active `exchange_position_key` in SQLite. Commit local active-trade lifecycle state and its matching journal event together; do not place exchange calls inside SQLite transactions.

**Consequences:**
- A mismatched or ambiguous store fails closed before migration, client construction, reconciliation, dashboard writes, or order paths. Existing closed history is preserved during an authorized legacy bind; current live-database binding remains a separate manual operation after independent acceptance.

### ADR-009: Explicit Exchange Submission Boundary (2026-07-20)

**Context:**
- The pinned CCXT Hyperliquid adapter enables builder fees by default and initializes a referrer before orders unless instance options prevent it.
- A post-fill slippage warning does not bound the price sent to the exchange.

**Decision:**
- For this runner, set `builderFee=False`, `approvedBuilderFee=False`, and `refSet=True`; do not revoke any pre-existing account authorization or attribution.
- A mean-reversion entry reuses its validated L2 top-of-book snapshot and submits one side-aware IOC limit: long at or below `best ask * 1.01`, short at or above `best bid * 0.99`. Precision rounding must stay inside that boundary. Do not use ticker last, refetch L2, chase, or widen the price.
- Keep the existing post-fill slippage journal as defensive evidence, not the primary entry-price control. Stops, market closes, and Trend GTC remain unchanged.

**Consequences:**
- Current-pin contract tests must spy the first order initialization and final action without network or real credentials.
- An unfilled IOC retains the existing no-confirmed-position recovery behavior; durable intent and retry semantics remain outside this decision.

### ADR-008: One-Shot Frozen-Price EXSPECIAL Trend Entry (2026-07-17)

**Context:**
- The accepted STRATEGY-11 entry could recreate hourly slope-plus-momentum candidates and wait for a near-middle/two-candle 5m rebreak. In a post-impulse sideways market, the middle could catch price and satisfy that path without a continuing trend.
- A BandWidth shock often precedes the canonical completed-1h slope transition, so using current or recent BandWidth expansion as a trend veto can remove the intended opportunity.
- The user selected a simpler order contract: detect the first canonical directional EXSPECIAL row, freeze its close, and wait at one fixed pullback price.

**Decision:**
- Supersede ADR-007 only for trend-entry authorization and order creation. Remove its trend-specific close momentum, hourly candidate expiry/refresh, near-middle zone, completed-5m rebreak, adverse-MR trend block, BandWidth trend veto, and market-entry path. Preserve ADR-007's `off | shadow | live` mode, source/management isolation, exchange-safety boundaries, and durable contemporaneous shadow comparison.
- Reuse `adverse_slope_take_profit.slope_n` and `exspecial_slope_threshold_pct`. On the first completed `1h` row of one continuous upward/downward EXSPECIAL episode, freeze close `F` and create at most one same-direction attempt: long `L = F * (1 - entry_pullback_pct)`, short `L = F * (1 + entry_pullback_pct)`. Do not refresh `F` or `L`, reconstruct a missed first-row order after a late start, or retry after a terminal fill/cancel in the same episode.
- `shadow` persists a virtual pending order and uses only future completed-5m low/high touches to simulate a fill at `L`. `live` places one system-owned exchange GTC limit. A live fill or partial fill wins a cancellation race; cancel the remainder, adopt actual quantity/average, and install protection immediately.
- Cancel an unfilled pending order when the completed-1h middle reaches `L` (`long >=`, `short <=`), the directional EXSPECIAL episode exits/reverses, or position/conflict/emergency/account/data safety fails. Cancel only the stored system order. BandWidth remains mean-reversion-only evidence and cannot authorize, veto, cancel, or resize the trend order.
- Expose only clear trend-local tuning names: `entry_pullback_pct`, `weakening_slope_threshold_pct`, and `initial_stop_distance_pct`. Trend management keeps the isolated completed-1h 5% monotonic stop, favorable-outer-band permanent break-even candidate, `0.18%` weakening threshold, reused canonical `0.09%` NORMAL floor, same-row weakening-plus-middle-cross exit, and no fixed take-profit.
- Keep the active rollout at `trend_riding.mode: shadow` until this replacement passes independent Acceptance and a later explicit rollout decision changes it.

**Alternatives Considered:**
- Keep the old entry as a compatibility fallback -> Rejected: two entry paths would make shadow attribution ambiguous and allow the superseded sideways trigger to leak back in.
- Keep BandWidth as a trend safety veto -> Rejected: BandWidth already protects mean-reversion and commonly expands before the slope reaches EXSPECIAL.
- Refresh the frozen price on every EXSPECIAL hour -> Rejected: converts one episode into repeated moving attempts and lets the middle chase price.
- Wait for another 5m rebreak or use a trend market order -> Rejected: the fixed GTC pullback already expresses the intended entry and gives an explicit price boundary.

**Consequences:**
- Trend entry becomes one durable pending-order state per directional EXSPECIAL episode, with explicit created/fill/cancel evidence and restart-safe terminal locking.
- Shadow fill timing is a completed-candle counterfactual, while live exchange fills may occur intrahour and therefore take priority over the next completed-1h cancellation check.
- Mean-reversion BandWidth/slope behavior remains unchanged; recorded BandWidth and real-trade outcomes remain comparison evidence only.
- Code, YAML, persistence, runtime, client, tests, and consensus must remove the superseded entry fields and branches rather than retain hidden compatibility behavior; independent Acceptance is required.

### ADR-007: YAML-Gated Trend Riding With Counterfactual Shadow Records (2026-07-15)

**Context:**
- The current mean-reversion entry path can correctly block some adverse entries through completed-1h BandWidth and slow-slope risk, but it cannot take the same-direction trend opportunity.
- Trend riding has different entry, stop, and exit semantics from the accepted NORMAL/SPECIAL/EXSPECIAL management lanes.
- The user needs a safe rollout mode and durable backend evidence for comparing the actual strategy without trend riding against the same period's hypothetical trend-riding signals.

**Decision:**
- Add one strategy-YAML mode, `trend_riding.mode`, with exactly `off`, `shadow`, and `live`. The schema default is `off`; the first active YAML value is `shadow`.
- `off` leaves new-entry behavior exactly on the accepted mean-reversion path. `shadow` runs the same pure trend evaluator and simulated lifecycle without blocking or mutating production decisions. `live` may block only the adverse mean-reversion side and may create a separately sourced trend position after all trend and generic safety gates pass.
- Mode gates only creation of new trend candidates or positions. Existing real trend positions always retain reconcile, protective-stop, trailing, and exit management. Existing open shadow positions continue simulation to a terminal outcome even after the mode changes; switching to `live` truncates the clean no-trend baseline at the switch time.
- Keep trend riding isolated from mean-reversion pending setups and its NORMAL/SPECIAL/EXSPECIAL management. Reuse completed features, exchange/account safety checks, order confirmation, protective-stop replacement, and zero-position close verification rather than duplicating those controls.
- Persist complete simulated trend trades in one dedicated SQLite table and reuse append-only trade events for state transitions. The contemporaneous actual runner remains the no-trend baseline while active mode is `shadow`; records must preserve calculation inputs, execution-eligibility evidence, stop/exit state, MFE/MAE, and simulated PnL provenance.
- When a trend candidate is active without a real or pending managed position, use completed-5m-aligned full polls instead of permanent 30-second full polling. Do not add a service, cache, queue, or second database.
- Keep the website read-only. Backend snapshot/API fields may expose mode and authoritative trend gate/state data; frontend code may only render those fields in a later frontend-owned task.

**Alternatives Considered:**
- Use `enabled` plus a second shadow boolean -> Rejected: creates invalid combinations and obscures which behavior is authoritative.
- Reuse mean-reversion pending setups or `live_shadow_triggers` -> Rejected: their one-hour RSI/setup and short-horizon outcome semantics do not match a multi-hour trend trade.
- Enable live orders immediately with no observation period -> Rejected for the first rollout: the new user instruction requests durable shadow comparison, while the three-state mode still preserves a one-value later activation path.
- Run full OHLCV polling every 30 seconds whenever shadow mode is configured -> Rejected: it adds avoidable API load when no trend candidate exists.

**Consequences:**
- The active runner initially remains behaviorally equivalent to the current strategy while collecting comparable trend evidence.
- A later switch from `shadow` to `live` requires one YAML change and runner restart, but no strategy rewrite.
- Execution must prove strict `off` parity, zero exchange mutation in `shadow`, source-aware management in `live`, restart-safe real and simulated positions, and independent Acceptance before the feature is treated as implemented.

### ADR-006: Read-Only Local Dashboard Boundary (2026-07-14)

**Context:**
- `frontend/` is a static Vinext prototype, while the accepted Python runner owns exchange calls, strategy state, SQLite writes, and order lifecycle.
- The browser needs exact live pipeline highlighting, runner visibility, manual-position labels, and immutable future archive views without becoming a second strategy evaluator.

**Decision:**
- Keep the website read-only. It may display `starting`, `running`, `stopped`, `error`, or `unknown`, but it cannot start, stop, signal, or otherwise control the runner.
- Keep the Python runner as the sole authority for strategy decisions and SQLite writes. Produce one small atomic dashboard snapshot from the actual runtime branches; the frontend renders backend-provided `passed` / `current` / `muted` states and never recomputes RSI, Bollinger Bands, slope, BandWidth, entry eligibility, or management stages.
- Match the dashboard contract to the current eight-node frontend shape with stable semantic node IDs. Slope classification is supporting regime/threshold evidence, not a separate entry node. The backend also supplies explicit entry, branch, and management connector states so the frontend never infers whether a path has been traversed from CSS or neighboring nodes.
- Expose a narrow Python standard-library API bound only to `127.0.0.1`. It reads the dashboard snapshot and opens live SQLite in read-only URI mode. Vinext same-origin route handlers may proxy `/api/dashboard/*` to this local API but must contain no trading or persistence logic.
- Determine runner liveness from the existing OS `fcntl` lock, with a tiny atomic lifecycle status only for distinguishing `starting`, `running`, and a safely summarized `error`. A free lock always wins over stale lifecycle data and means `stopped`.
- For `manual_adopted`, gray strategy entry steps 1-7 and highlight only step 8 plus the active management chain. Add right-side `手动接管` and `手动加仓` tags from persisted source/event evidence.
- Generate immutable SVG snapshots only for trades archived after this feature lands. Existing archives remain listable with `snapshot_available = false`; do not reconstruct unknown historical paths.

**Alternatives Considered:**
- Let the frontend read/write SQLite or recompute strategy state -> Rejected: duplicates live authority and creates safety and consistency risks.
- Add FastAPI, a message queue, D1, or a second database -> Rejected: unnecessary for a three-symbol local dashboard with 30-second polling.
- Add runner start/stop controls now -> Rejected: no agreed process supervisor or ownership boundary exists, and monitoring does not require control authority.

**Consequences:**
- Dashboard CPU cost stays negligible because it maps existing state and serves a small snapshot instead of rerunning indicators or scanning the full event history.
- Backend and frontend work remain coupled by an explicit JSON contract but isolated from order placement and configuration writes.
- Snapshot generation and API failures must never block trade management or trade archival; the UI retains the last confirmed state and marks data unavailable or stale.

### ADR-005: Three-Regime Position Management And BandWidth Entry Guard (2026-07-14)

**Context:**
- A completed-1h middle-band slope can lag the start of a violent move, while BandWidth may expand on the first adverse candle.
- A global middle-band take-profit would prevent profitable NORMAL positions from crossing the middle and entering the existing midband-follow trend stage.
- SPECIAL and EXSPECIAL need different risk behavior without restoring the old `bbmr_v3_2` multi-filter state machine.

**Decision:**
- Treat `docs/strategy_consensus/bbmr_trailing_stop_v1.md` as the full target behavior.
- NORMAL uses the full staged trailing-stop chain with no middle-band TP.
- SPECIAL uses strict `32/68` RSI, `2x`, and a rolling completed-1h middle-band TP bounded by entry price while the protective/trailing stop remains active.
- EXSPECIAL blocks new strategy entries. Existing managed positions enter sticky defensive mode: freeze the current protective stop, stop later trailing updates, and use a rolling completed-1h half-band target with `exspecial_near_middle_frac = 0.5` and no entry-price floor.
- Add a per-symbol completed-1h BandWidth entry guard. Block only `HIGH_EXPANDING`, initially defined as 120h percentile `>= 80` and 1h expansion `>= 10%`; invalid BandWidth also blocks. Record allowed and blocked setup evidence for later tuning.
- Make the completed 5m close break of the previous completed 5m high/low the production entry trigger. Move the 5m middle-band trigger and three-bar 5m RSI direction trigger to shadow-only evaluation.
- Missing or invalid slope uses strict RSI, `2x`, and SPECIAL management for a new position; an existing position preserves its last valid regime and never clears EXSPECIAL because data is missing.
- Split the legacy `adverse_slope_take_profit.near_middle_frac` into `special_near_middle_frac` and `exspecial_near_middle_frac`. The authorized migration preserves `0.0` for SPECIAL and sets EXSPECIAL to `0.5`; thereafter the two valid YAML values are independently user-editable and authoritative.

**Alternatives Considered:**
- Use a middle-band TP in every regime -> Rejected: removes the NORMAL trend-running path and makes later trailing stages unreachable.
- Freeze the 1h middle when EXSPECIAL activates -> Rejected: a continuing adverse move can leave the target unreachable.
- Remove the protective stop in EXSPECIAL -> Rejected: a software TP or network failure would leave the position unprotected.
- Block every high-BandWidth setup -> Rejected: high but contracting volatility is not the same risk as active expansion.

**Consequences:**
- The strategy has one setup chain, one active BandWidth entry guard, and three explicit management regimes.
- SPECIAL sacrifices outer-band continuation while active; EXSPECIAL may intentionally realize a smaller loss to avoid waiting for the original stop.
- Implementation requires strategy-critical config, persistence, runtime, observability, and focused test changes followed by independent acceptance.
- Legacy YAML using the single `near_middle_frac` key must be migrated explicitly and rejected afterward rather than silently applied to both regimes.
- Existing code and config may lag this ADR until the corresponding execution task passes acceptance.

### ADR-004: Separate Execution Evidence From Acceptance Review (2026-07-04)

**Context:**
- Small and medium live-runner tasks were spending too many tokens repeating the same scope, test list, and project rules across Planning, Execution, and Acceptance.
- Execution Zone needs to verify what it changed, but that does not replace independent Acceptance Zone review.

**Decision:**
- Every Execution task gets a short Acceptance Contract. A separate Acceptance pass is required only for risky, user-critical, or explicitly requested work.
- Execution Zone self-check is limited to evidence: changed files, scope boundaries honored, commands run, manual checks if any, skipped scope, and blockers.
- Acceptance Zone should review against the Acceptance Contract, execution evidence, and current diff, focusing on blind spots and regression risk rather than repeating the full task prompt.
- Acceptance Zone is fully read-only and returns only `通过 / 不通过` plus evidence. After receipt, Planning Zone or Execution Zone records the verdict verbatim in `issues.md`; Acceptance Zone never edits code or documentation.
- Full `/private/tmp` handoffs remain reserved for complex, ambiguous, failed, or architecture-affecting work.

**Alternatives Considered:**
- Keep repeating the full execution prompt to Acceptance Zone -> Rejected: wastes context and repeats stable rules.
- Let Execution Zone serve as its own final acceptance -> Rejected: removes independent review.

**Consequences:**
- Small and medium tasks can use shorter prompts and lighter handoffs.
- Acceptance stays independent while avoiding duplicate long checklists.
- The project keeps an auditable verdict in `issues.md` without weakening the Acceptance Zone's read-only boundary.
- Future workflow prompts should separate stable context from this-turn required reading.

### ADR-003: Indicator Alignment Requires Same Exchange Candle Source (2026-07-01)

**Context:**
- Hyperliquid and most exchange APIs expose OHLCV candles but not chart indicator values such as RSI.
- The active live strategy compares locally computed RSI with thresholds and expects those readings to match the exchange website chart closely.

**Decision:**
- Any RSI value used for live trading must be computed from OHLCV candles fetched from the same exchange environment whose chart is being matched.
- Hyperliquid testnet live trading uses Hyperliquid testnet candles; Hyperliquid mainnet live trading uses Hyperliquid mainnet candles.
- Future exchange integrations must compute RSI from that exchange's own candles before claiming chart alignment.
- RSI formula, method, warmup/history length, and completed-candle handling must be configurable and validated against manually sampled chart readings before live use.

**Alternatives Considered:**
- Use candles from another exchange or cached research data -> Rejected: RSI cannot reliably match the target website chart.
- Use local RSI without chart calibration -> Rejected: prior validation found indicator mismatch risk.

**Consequences:**
- Strategy portability requires per-exchange indicator calibration.
- Backtest or third-party candles are not acceptable as live indicator authority for chart-matching RSI decisions.

### ADR-002: Keep Hyperliquid Live Runner Independent From Backtest Package (2026-06-30)

**Context:**
- The live runner needs trailing setup, confirmation, entry-signal, and feature-building helpers from the trailing strategy.
- Mainline should not import the broad research/backtest package just to run Hyperliquid testnet live execution.

**Decision:**
- Put the live-required trailing helpers in neutral modules: `src/bbmr/trailing.py` and `src/bbmr/trailing_features.py`.
- Keep the Hyperliquid live runner under `src/bbmr/live/` and make it depend on those neutral helpers, not `src/bbmr/backtest/*`.

**Alternatives Considered:**
- Copy `src/bbmr/backtest/` into mainline -> Rejected: brings research architecture into the live integration.
- Keep live imports pointing at backtest helpers -> Rejected: makes backtest package a runtime dependency.

**Consequences:**
- Mainline live execution can use the trailing strategy without merging the full backtest stack.
- Focused tests must protect the shared trailing helper timing behavior.

### ADR-001: Use Project Notes for AI Handoffs and Worklog (2026-06-25)

**Context:**
- The project needs continuity across planning-zone and execution-zone AI work.
- Planning should produce handoffs, while execution should follow handoffs without expanding scope.

**Decision:**
- Store project memory in `docs/project_notes/`.
- Use `docs/project_notes/issues.md` as the active worklog for planning progress, handoffs, execution progress, blockers, and completion notes.
- Use `AGENTS.md` as the first-read instruction file for AI agents.

**Alternatives Considered:**
- Keep notes only in chat -> Rejected: hard to reuse across sessions.
- Add a separate automation system -> Rejected: unnecessary for the current need.

**Consequences:**
- Agents have a stable place to read and update project context.
- The process depends on agents consistently following `AGENTS.md`.
