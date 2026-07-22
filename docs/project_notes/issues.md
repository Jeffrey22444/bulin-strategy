# Worklog

Track planning, handoffs, execution progress, blockers, and completed work here.

## Current Summary

- **Current phase**: `STRATEGY-16` passed independent Acceptance; `STRATEGY-16-GIT-CLOSEOUT` is routed to Maintenance.
- **Current recommended next task**: Maintenance inventories the three related top-level directories, resolves the canonical-tree/path-dependency boundary, then commits and normally pushes only the latest accepted system to `origin/main` if every safety gate passes.
- **Latest accepted slice**: `STRATEGY-16` passed independent Acceptance. This is source acceptance only; it does not prove the current runner loaded the accepted source.
- **Open blockers**: Maintenance must stop before commit/push on divergent/unknown copies, unresolved path dependencies, unaccepted worktree content, active-runtime relocation risk, secret/runtime artifacts, failed verification, or non-fast-forward remote state.
- **Last updated**: 2026-07-22

### 2026-07-22 - STRATEGY-16 Local Trend Watch Execution
- **Status**: Completed; independent Acceptance pending
- **Zone**: Execution
- **Evidence**: First-EXSPECIAL Trend creation now persists a local F/L/TTL watch with no same-cycle leverage or GTC. Completed-1h directional-NORMAL and middle-cross checks cancel before touch; a fresh valid L2 checks middle invalidation before exact-L submission. Shadow uses the same conservative order with future completed-5m low/high and taker-on-touch costs. Waiting opposite-MR takeover reuses the invalidation gates; started protected close/cleanup latches invalidation, completes flat/owned-stop cleanup, and remains flat without Trend entry.
- **Verified**: Temporary SQLite/fake-exchange focused regressions cover local creation, live middle-first cancellation, completed-middle cancellation, shadow middle-first cancellation, waiting-takeover cancellation, started-takeover flat convergence, exact-L order, fill/recovery, and prior response-loss paths. No real runner, database, credential, exchange, mainnet, YAML, frontend, lock, or Git write was used.
- **Boundary**: No change to F/L formulas, TTL renewal, reservations, MR strategy path, stop/TP management, schema, active YAML values, or runner state.
- **Rework 1 Evidence**: Acceptance found the managed-MR runner branch returned before `waiting_opposite_mr` could call the existing takeover state machine. The protected `source=strategy` branch now calls that same state machine after its existing management work, emits its transitions, and reuses the existing post-mutation account refresh/later-symbol block. New temporary-SQLite/fake-exchange `_poll_once` regressions prove L touch reaches reduce-only MR close with zero Trend leverage/GTC until flat plus owned-stop cleanup, while completed-middle invalidation retains the MR/system stop with zero mutation. Independent Acceptance remains required.

### 2026-07-22 - STRATEGY-16 Post-Acceptance Git/Workspace Closeout Registration

- **Task ID**: `STRATEGY-16-GIT-CLOSEOUT`
- **Status**: Activated and routed to Maintenance after independent Acceptance passed.
- **Acceptance Return Verbatim**: `完成了执行和验收，进入下一步` (`STRATEGY-16` final review result: `通过`).
- **Route**: Planning handoff `/private/tmp/bbmr_strategy16_git_workspace_closeout_2026-07-22.md`; Maintenance thread `019f7f07-ac98-7992-90e6-118456af4591`.
- **Authorized future scope**: Maintenance inventories BBMR-related top-level folders under `/Users/jeffrey/Documents` (treating the user's `/documents` reference as this macOS Documents directory), including the known `布林带策略_frontend_git_backup_2026-07-20`; classifies production/backend/frontend content separately from backups, archives, runtime data, and generated artifacts; compares exact content and provenance; moves only confirmed canonical production/frontend content into `/Users/jeffrey/Documents/布林带策略`, without overwrite or deletion; and audits all absolute and relative path dependencies.
- **Code boundary**: If resolving a path requires edits to production code, tests, YAML, or frontend source, Maintenance stops and returns exact evidence to Planning for a separate Execution plus Acceptance slice. Maintenance must not silently patch those files.
- **Git closeout**: Once the canonical tree is complete and accepted, Maintenance verifies the remote, branch, worktree, staged/untracked files, nested Git metadata, secrets, runtime data, and generated artifacts; runs relevant tests/builds and path searches; stages only the intended files; creates a normal commit; and pushes the latest accepted system to the existing GitHub remote.
- **Safety boundary**: No force push, history rewrite, destructive cleanup, blind merge/move, overwrite, secret publication, runtime SQLite/log/artifact publication, or ambiguous branch/remote action. Destination conflicts, divergent duplicates, unknown ownership/provenance, active use of a relocation target, uncertain path dependencies, or missing Acceptance return to Planning.
- **Planning preflight**: Read-only top-level inventory found only the canonical project plus `布林带策略_frontend_git_backup_2026-07-20` and `布林带策略_ponytail_backup_2026-07-20`. Git is on `main` tracking the existing `Jeffrey22444/bulin-strategy` origin with a broad accumulated dirty tree. Planning performed no move, stage, commit, push, process/runner action, SQLite/exchange write, code/YAML/test/frontend edit, dependency change, or remote mutation.
- **Maintenance M1 Blocker**: Directory inventory/path audit passed with zero moves; both external backups remain intentionally external. Python full suite and frontend test/build/render passed. Exact allowlist staging stopped because untracked accepted `docs/repository_audit.md` has two trailing spaces on each of lines 3 and 4. Maintenance restored the index to empty and made no commit/push or runtime change.
- **Planning R1 Decision**: Keep the accepted audit document in the publish set and authorize Maintenance to remove only those four trailing spaces, prove whitespace-only equivalence, then resume the original exact staging/normal-push contract. R1 handoff: `/private/tmp/bbmr_strategy16_git_workspace_closeout_r1_2026-07-22.md`. No separate strategy/code Acceptance is required for this mechanical documentation formatting correction.

### 2026-07-21 - STRATEGY-15 Trend Takeover Execution
- **Status**: Completed; independent Acceptance pending
- **Zone**: Execution
- **Evidence**: Added strict takeover mode/TTL config, testnet `live/live/6` and `1.20` YAML values, durable pending expiry/takeover linkage, signed-slope validity and terminal-first renewal, and a local waiting -> close-MR -> flat-stop-cleanup -> fixed-L GTC flow. Partial MR remainders continue reduce-only closing on subsequent active polls without a new touch.
- **Verified**: Temporary SQLite/fake-exchange regressions cover active values, phase persistence, signed reversal/TTL renewal, same-symbol MR-intent exclusion, opposite protected MR waiting, off/shadow zero mutation, response-loss restart recovery, partial close continuation, old-stop ordering, post-fill 1h bucket, and account-order call propagation. `tests/live/test_live_config.py tests/live/test_state_store.py tests/live/test_trailing_runtime.py tests/live/test_live_run.py tests/live/test_hyperliquid_client.py -q`, `tests/test_config.py tests/live/test_trailing_helpers.py -q`, full `tests -q`, and `git diff --check` exited 0.
- **Boundary**: No frontend, dependency/lock, runner, credential, real SQLite, real exchange, mainnet, or Git write action. Disk YAML does not prove any current runner loaded it.

### 2026-07-21 - STRATEGY-15 Minimal Rework: Waiting Ownership Revalidation
- **Status**: Completed; independent Acceptance pending
- **Evidence**: A waiting opposite-MR takeover now reads fresh exchange positions and reuses the linked-MR eligibility check before a touch can persist `takeover_triggered`. A post-watch `manual_size_changed` terminalizes the pending as `takeover_eligibility_lost`; no close, leverage, Trend GTC, or old-stop cancel occurs. Started close/cleanup phases remain unchanged.

### 2026-07-20 - AUDIT-G7 Ponytail Cleanup Planning
- **Status**: Planned; D1-D4 confirmed and `AUDIT-G7-M0` ready for manual initial transfer
- **Zone**: Planning
- **Description**: Keep G7 as one independently accepted cleanup Goal with three controlled phases: Maintenance first moves the exact untracked frontend starter paths to a recoverable external backup; Execution then removes the unsupported Phase-1A/starter/config/shim/dead-member/direct-dependency scope in one persistent `/goal`; Maintenance finally regenerates both locks before final Acceptance.
- **Handoff**: `/private/tmp/bbmr_audit_g7_ponytail_cleanup_handoff_2026-07-20.md`
- **User Decisions**: Delete unsupported `bbmr_v3_2` without an archive; back up then remove unused frontend starter residue; reject legacy config strictly while preserving real safety gates; remove six direct dependencies without retained-version upgrades.
- **Current Corrections**: Retain active `src/bbmr/indicators.py` and remove only its direct NumPy use; retain G5-used `active_trend_pendings()`; remove only verified dead `LiveRuntime.pending` and `HyperliquidClient.missing_credentials`.
- **Routing**: The user manually transfers M0 and later phase starts. Execution directly routes Planning's verbatim implementation Acceptance Contract plus evidence to Acceptance; Acceptance routes minimal rework directly to Execution or the exact next-step message to Planning. No automation window is used.
- **Boundary**: Planning changed only this worklog and the temporary handoff. No business code, tests, YAML, frontend, locks, environment, Git, runner, database, or exchange state was modified.

### 2026-07-20 - AUDIT-G7-E Ponytail Cleanup Execution
- **Status**: Completed; independent implementation-gate Acceptance passed
- **Zone**: Execution
- **Evidence**: Verified all eight M0 source paths remain absent while their external backup paths exist. Removed the approved Phase-1A production/test/YAML island, duplicate adapter, stale frontend starter usage, inert config fields/fallback, runner optional dispatch, two dead members, and six direct dependencies. Active trailing schema now rejects absent/unknown strategy identities and removed keys.
- **Verified**: Focused config/indicator/live tests, full Python suite, and frontend build/render tests pass. Searches find no removed production/test/config/frontend consumer, direct NumPy import, or scoped runner `getattr` shim. Ponytail scoped review: `Lean already. Ship.`
- **Boundary**: No lockfile regeneration, package installation, Git operation, runner, real SQLite, credentials, exchange, mainnet, trend-mode, or external-backup mutation. `uv.lock` and `frontend/package-lock.json` intentionally await M1.
- **Acceptance**: 通过 — only M1 is authorized; G7 is not yet closed.

### 2026-07-20 - AUDIT-G7-M1 Lock Closeout Planning
- **Status**: Ready for manual transfer to Maintenance
- **Zone**: Planning
- **Handoff**: The active M1 Amendment is embedded near the top of `/private/tmp/bbmr_audit_g7_ponytail_cleanup_handoff_2026-07-20.md`.
- **Current Mismatch**: `pyproject.toml` removed direct NumPy while `uv.lock` still lists the old root specifier; `frontend/package.json` removed five direct packages while the root and package nodes remain in `frontend/package-lock.json`.
- **Procedure**: Generate both candidates in isolated temporary copies, mechanically prove no retained-version/source/hash/integrity drift or new nodes, replace only the two locks, then frozen-sync/clean-install and test in temporary environments.
- **Preflight**: Planning currently sees no repository runner, acceptance, frontend dev, or workerd process; `git diff --check` passes. Maintenance must independently recheck and must not stop processes.
- **Boundary**: No manifest/source/test/YAML/frontend-source/backup/repository-environment/Git/runner/database/exchange change is authorized. Maintenance returns evidence to Planning and does not self-accept or start final Acceptance.

### 2026-07-20 - AUDIT-G7-M1 Lock Generation Stop And E-R1 Diagnosis
- **Status**: M1 paused after authorized lock replacement; E-R1 ready for manual transfer to Execution
- **Zone**: Maintenance / Planning
- **Retained Locks**: `uv.lock` hash `b6b2cf935f15d460b95c11308bdfba2c70d6cec25074926206e2973f11ca61f5`; `frontend/package-lock.json` hash `cc977b9086cdaf592999b2a63b49b436e3bb45d91121ccef7da901c44d3f0fb8`. Both manifests stayed unchanged.
- **Passed Evidence**: Python frozen sync and full suite passed with NumPy `2.5.0` on Python 3.12 and no `2.5.1`. npm graph is 710→590 with zero new nodes and zero retained version/resolved/integrity/marker drift; clean install and build passed.
- **Blocker**: Render suite was `2/3`; Vinext generated a font-preload `Link` containing the absolute Chinese workspace path and Node Headers rejected `布` as non-ByteString.
- **Planning Diagnosis**: Reproduced identically on Node 26 and bundled Node 24. A read-only header probe identified `frontend/.vinext/fonts` as the value source; suppressing only that header restored HTTP 200 and every live-flow assertion. `next/font` Geist variables are unused because native CSS already owns the font stack.
- **Decision**: Reopen only `AUDIT-G7-E-R1` to remove unused Geist loaders/body class in `frontend/app/layout.tsx`. Preserve locks and manifests exactly; no header workaround, runtime pin, test change, or M1 regeneration.
- **Process Deviation**: Maintenance used `rm -rf` once only on its task-owned `/private/tmp` candidate directory. No repository, backup, or persistent environment path was affected. The prohibited operation must not recur.
- **Temporary Evidence**: `/private/tmp/bbmr-audit-g7-m1.1qrv4Z` must remain until final G7 closure.
- **Boundary**: Planning diagnosis was read-only apart from this worklog/handoff. No source/test/YAML/manifest/lock/backup/Git/runner/database/exchange mutation was performed.

### 2026-07-20 - AUDIT-G7-E-R1 Acceptance And M1-R2 Resume
- **Status**: E-R1 completed and independently passed; M1-R2 ready for manual transfer to Maintenance
- **Zone**: Execution / Acceptance / Planning
- **E-R1 Evidence**: Only `frontend/app/layout.tsx` changed. Removed unused `next/font` Geist loaders and body variable class; preserved metadata, favicon, Chinese lang, children, and native CSS font stack. Node 26 in the real Chinese workspace passed Vinext build and rendered tests `3/3`.
- **Acceptance**: 通过 — only M1 resume validation is authorized; G7 remains open.
- **Hash Recheck**: Planning confirmed `uv.lock b6b2cf93...`, `frontend/package-lock.json cc977b90...`, `pyproject.toml 9ceae492...`, and `frontend/package.json 3f747a17...`; `git diff --check` passes.
- **R2 Scope**: Do not regenerate locks. Preserve the original M1 evidence root, create a new temporary frontend copy, perform offline clean `npm ci`, build/render `3/3`, recheck existing Python/lock/backup/process/Git boundaries, and return the M1 completion marker.
- **Boundary**: No new source/test/YAML/manifest/lock/backup/repository-environment/Git/runner/database/exchange change is authorized. No recursive deletion may be used.

### 2026-07-20 - AUDIT-G7-M1-R2 Maintenance Closure And Final Acceptance Activation
- **Status**: Maintenance closeout complete; final independent read-only `AUDIT-G7` Acceptance ready for manual transfer
- **Zone**: Maintenance / Planning
- **Completion Marker**: `AUDIT-G7_LOCK_CLOSEOUT_COMPLETE`
- **Retained Hashes**: `uv.lock b6b2cf93...`, `frontend/package-lock.json cc977b90...`, `pyproject.toml 9ceae492...`, and `frontend/package.json 3f747a17...`; neither lock was regenerated, replaced, rolled back, or normalized in R2.
- **Frontend Evidence**: In `/private/tmp/bbmr-audit-g7-m1-r2.pGN5G7`, offline clean `npm ci` succeeded under Node 26, Vinext build passed, and rendered tests passed `3/3`; generated output contains no absolute Chinese repository path and the actual response had status 200 with no font-preload `Link` header.
- **Python And Graph Evidence**: Existing frozen/full-suite proof remains valid because `uv.lock` is unchanged. Maintenance and Planning task-local offline lock checks pass; NumPy remains `<3.12 = 2.4.6`, `>=3.12 = 2.5.0`, with no `2.5.1`. npm root maps match the manifest; prior 710 to 590, zero-new-node, zero-retained-drift proof remains applicable.
- **Backup And Boundary Check**: Planning confirmed all eight backup paths and 11 files remain present, `.env` is regular `0600` without reading contents, staged diff is empty, and `git diff --check` passes. Planning's sandbox denied `ps`, so no-process status relies on Maintenance's R2 evidence; Planning did not signal or start anything.
- **Handoff**: `/private/tmp/bbmr_audit_g7_ponytail_cleanup_handoff_2026-07-20.md` now activates the unchanged Final G7 Acceptance Contract.
- **Boundary**: No business code, test, YAML, frontend, manifest, lock, backup, repository environment, Git, runner, database, credential, or exchange state was modified by Planning.

### 2026-07-20 - AUDIT-G7 Final Independent Acceptance And Repository-Audit Closure
- **Status**: Completed; G7 and the repository-audit remediation Goal sequence are closed
- **Zone**: Acceptance / Planning
- **Acceptance Return Verbatim**: `完成了执行和验收`
- **Closure**: The final Planning-authored G7 Acceptance Contract passed after accepted M0, E, E-R1, and M1-R2 evidence. `AUDIT-G1` through `AUDIT-G7` have now each completed independent Acceptance.
- **Retained State**: The external Ponytail backup and `/private/tmp/bbmr-audit-g7-m1.1qrv4Z` plus `/private/tmp/bbmr-audit-g7-m1-r2.pGN5G7` remain untouched for recoverability/evidence.
- **Next-Step Boundary**: No new Goal, Git/mainline operation, backup deletion/restoration, temporary-evidence cleanup, runner action, or exchange action is authorized by the pass. Planning waits for an explicit user decision.
- **Handoff**: `/private/tmp/bbmr_audit_g7_ponytail_cleanup_handoff_2026-07-20.md` is closed and retained as the audit trail.

### 2026-07-20 - SAFETY-8 Closed-History Protection-Recovery Filter Planning
- **Status**: Planned; routed to Execution with independent Acceptance required
- **Zone**: Maintenance diagnosis / Planning
- **Symptom**: BTC, ETH, and SOL each emitted `strategy entry blocked: protective-stop recovery active` even though the live database contained no active managed trade or stop-replacement intent.
- **Read-Only Reproduction**: `live_stop_replacements=0`; all 25 `live_trades` rows are `status='closed', protection_status='unknown'`. The current predicate matches 25 rows, while the same recovery predicate restricted to non-closed lifecycle rows matches 0.
- **Root Cause**: G4 added `protection_status` with legacy default `unknown`, while `has_protection_recovery()` checked recovery truth without excluding terminal `closed` history. `_archive_trade()` correctly preserves the historical protection field and is not the repair target.
- **Decision**: Change only the trade-side query to require `status != 'closed'` before considering `entry_unprotected` or `protection_status IN ('recovery','unknown')`. Excluding only the known terminal status preserves fail-closed behavior for every non-closed or future unexpected lifecycle status. Keep any `live_stop_replacements` row account-blocking.
- **Required Regression Boundary**: Closed `unknown/recovery` history must not block; non-closed `entry_unprotected/unknown/recovery` and any stop-replacement intent must still block account-wide. Add a runtime-seam test proving closed history reaches the next existing entry guard instead of the CRITICAL recovery branch.
- **Out Of Scope**: No live SQLite mutation/migration/cleanup, archive-field rewrite, safety-gate weakening, YAML/frontend/dependency/lock/Git change, runner restart/signal, credential read, or exchange action.
- **Routing**: Execution receives the task and verbatim Acceptance Contract. Execution routes completion evidence plus that contract to Acceptance; Acceptance failure routes the smallest same-ID rework directly to Execution, while pass routes `完成了执行和验收，进入下一步` to Planning. Maintenance remains read-only and does not implement production code.

### 2026-07-20 - SAFETY-8 Closed-History Protection-Recovery Filter Execution
- **Status**: Completed; independent Acceptance passed
- **Zone**: Execution
- **Evidence**: `has_protection_recovery()` now excludes only `status='closed'` before preserving the existing non-closed unsafe-state and stop-replacement fail-closed checks. Temporary SQLite regressions cover closed `unknown/recovery`, active `entry_unprotected/unknown/recovery`, and replacements; the runtime seam reaches the existing exchange-position guard for closed-only history.
- **Verified**: `./.venv/bin/python -m pytest tests/live/test_state_store.py tests/live/test_trailing_runtime.py -q`, `./.venv/bin/python -m pytest tests -q`, and `git diff --check` passed.
- **Boundary**: No runtime call-site, archive behavior, live SQLite, strategy/YAML/frontend/dependency/lock/Git, runner, credential, or exchange change.
- **Acceptance**: `完成了执行和验收，进入下一步`

### 2026-07-20 - SAFETY-8 Acceptance And Runtime Assessment Routing
- **Status**: Accepted; routed to Maintenance for read-only runtime assessment
- **Zone**: Acceptance / Planning / Maintenance
- **Acceptance Return Verbatim**: `完成了执行和验收，进入下一步`
- **Next Step**: Maintenance identifies whether the accepted source is loaded by the current runner using process identity/start-time and read-only evidence only. It must not modify production code, SQLite, Git, runner, credentials, or exchange state.
- **Decision Boundary**: If a start or restart is needed, Maintenance reports the exact process/command/impact and waits for explicit user authorization; Acceptance does not authorize runtime mutation.

### 2026-07-20 - SAFETY-8 Runtime Verification Closure
- **Status**: Completed; active runner verified to have loaded the accepted source
- **Zone**: Maintenance / Planning
- **Process Evidence**: Runner PID `74794` started at `2026-07-20 22:56:30` from the repository with the order-capable testnet command, after the accepted `state_store.py` modification time `22:51:57`. Dashboard PID `13789` remained separately active; no Acceptance process was present.
- **Read-Only DB Evidence**: `live_stop_replacements=0`, non-closed recovery rows `=0`, and closed/unknown history `=25`; no database write, cleanup, or migration occurred.
- **Runtime Evidence**: Lifecycle and current snapshots advanced through `23:00:24` with status `running`. BTC/ETH/SOL each reported `waiting for 1h setup` / `no_1h_setup`; the false `protective-stop recovery active` block did not recur.
- **Conclusion**: Maintenance state `C` is established. The pre-fix 22:39 CRITICAL output is historical; the accepted predicate is loaded and no start/restart authorization is needed.
- **Boundary**: Maintenance did not signal processes or modify production code, tests, documentation, YAML, frontend, locks, SQLite, Git, credentials, or exchange state. No further routing is active.

### 2026-07-20 - AUDIT-G7-M0 Frontend Process Stop
- **Status**: Blocked safely; no Maintenance write occurred
- **Zone**: Maintenance / Planning
- **Stop Evidence**: All eight source paths exist, the external backup root does not exist, and the pre-move manifest contains 20 items with digest `bd6131e6ded6bcd59ea2e4f203dabc8c06b9e36c18b3bfb52eab517c0e0c0b8f`. Maintenance detected two active repo frontend dev trees and stopped under the contract before moving anything.
- **Planning Read-Only Check**: Process group `46472` is `npm run dev` → PID `46485` `vinext dev` → PID `46537` `workerd`; process group `66982` is `npm run dev` → PID `67001` `vinext dev` → PID `67009` `workerd`. Both parents are currently adopted by PID 1 and began on 2026-07-14.
- **Decision Required**: Stopping these exact frontend-only process groups temporarily takes the local frontend development UI offline. It must not be inferred as authorization to stop the Python dashboard, BBMR runner, or any exchange-facing process.
- **Boundary**: No path was moved, no backup root was created, and no source, frontend content, lock, Git, runner, database, or exchange state changed.

### 2026-07-20 - AUDIT-G7-M0 Resume Amendment R1
- **Status**: Ready for manual transfer to Maintenance
- **Zone**: Planning
- **User Authorization**: Gracefully stop only frontend process groups `46472` and `66982`, then resume M0.
- **Safety Contract**: Maintenance must revalidate current PID/PGID/command/descendants before signaling, send only `SIGTERM`, wait at most 15 seconds, and stop without `SIGKILL` if anything survives or identity is uncertain. It must not stop the Python dashboard, BBMR runner, exchange-facing processes, or other workspace processes.
- **Resume Gate**: After exit, prove no repository frontend dev process remains and the original 20-item manifest still has digest `bd6131e6ded6bcd59ea2e4f203dabc8c06b9e36c18b3bfb52eab517c0e0c0b8f` before any move.
- **Handoff**: Resume amendment is embedded at the top of `/private/tmp/bbmr_audit_g7_ponytail_cleanup_handoff_2026-07-20.md`; all other M0 boundaries and completion evidence remain unchanged.
- **Boundary**: Planning did not signal any process, move any path, create the backup root, or modify business code, tests, YAML, frontend content, locks, Git, runner, database, or exchange state.

### 2026-07-20 - AUDIT-G7-M0 Planning Closure C1
- **Status**: Completed after evidence review; `AUDIT-G7_PREBACKUP_COMPLETE`
- **Zone**: Maintenance / Planning
- **Backup Evidence**: Both Maintenance manifests contained 20 items with identical digest `bd6131e6ded6bcd59ea2e4f203dabc8c06b9e36c18b3bfb52eab517c0e0c0b8f`; all eight sources are absent and all eight backup targets exist. Planning independently confirmed the backup contains 11 files plus its expected directory layout and no repository frontend dev process remains.
- **Process Evidence**: Each authorized frontend process group received one graceful `SIGTERM` and exited in about one second; no `SIGKILL`, Python dashboard, runner, or exchange-facing process was touched.
- **Tracked-Diff Diagnosis**: Maintenance correctly stopped on pre/post digest mismatch (`48ebba...` → `d68987...`). The raw pre-diff was not retained, so its exact source cannot be reconstructed. Current evidence excludes an M0 tracked mutation: the parent index has no staged diff and is unchanged since 2026-07-12; `git ls-files frontend` is empty; all modified tracked-file mtimes predate the M0 resume; five consecutive current binary diffs are stable at `d68987...`; `git diff --check` passes.
- **Decision**: Treat the mismatch as a baseline-capture inconsistency. Do not restore the backed-up starter paths and do not clean/reset the worktree. `d68987...` is the authoritative whole-worktree tracked baseline entering E, while Execution must report only its scoped G7 changes.
- **Boundary**: No business code, test, YAML, manifest, lock, Git index/commit, runner, database, or exchange mutation was added by Planning's verification. G7-E still requires independent implementation-gate Acceptance and does not authorize M1 or final closure.

### 2026-07-20 - AUDIT-G6-E Operational Governance Execution
- **Status**: Completed; independent implementation-gate Acceptance passed
- **Zone**: Execution
- **Evidence**: Dry-run now uses a deterministic isolated DB/lock/dashboard namespace; recoverable restart-time candle failure preserves pending setup, while post-store fatal errors record sanitized CRITICAL lifecycle evidence and rethrow. Testnet acceptance cleanup confirms zero before cancelling only its owned stop. PnL is exact only for a matching close identity and exact quantity; otherwise unknown. Dashboard snapshots serialize runner traces and frontend symbols come from the backend.
- **Verified**: Fake/temp-only focused Python suite, full Python suite, frontend test suite, and `git diff --check` passed. Final test paths stub default environment loading or use temporary env files; no `.env` permission change, dependency/lock change, `frontend/.git` or Git-state action, real DB/runner/exchange/mainnet call, YAML change, or Maintenance/G7 work.
- **Acceptance**: 完成了执行和验收，进入下一步

### 2026-07-20 - AUDIT-G6-M First-Lock Resolver Stop And Resume
- **Status**: Planned resume; no Maintenance write occurred before the stop
- **Zone**: Planning / Maintenance
- **Stop Evidence**: Runner PID 2443 was absent and only the independent dashboard remained. Plain `uv lock --dry-run` selected NumPy `2.5.1` plus `2.4.6`, so Maintenance correctly stopped under the no-upgrade contract. `.env` stayed `0644`; no `uv.lock` was created; `frontend/.git`, source, Git index, runner, and exchange were unchanged.
- **Diagnosis**: The universal lock covers declared Python `>=3.11`; NumPy `2.5.0` requires Python `>=3.12`, so Python 3.11 needs a `2.4.6` fork. A Planning dry-run proved that marker-aware exact package preferences preserve the complete current Python 3.12 environment, select NumPy `2.5.0` for Python `>=3.12`, retain `2.4.6` only for Python 3.11, and require no `pyproject.toml` edit.
- **Resume Handoff**: `/private/tmp/bbmr_audit_g6_maintenance_closeout_handoff_2026-07-20.md` now contains the superseding M1 amendment and exact no-upgrade lock procedure.
- **Boundary**: The revised task still permits only `.env` mode `0600`, root `uv.lock`, temporary verification/cache directories, and the recoverable `frontend/.git` move. G7 remains blocked.

### 2026-07-20 - AUDIT-G6-M Maintenance Closeout
- **Status**: Completed; final independent read-only G6 closure Acceptance passed
- **Zone**: Maintenance / Planning
- **Completion Marker**: `AUDIT-G6_MAINTENANCE_COMPLETE`
- **Environment Evidence**: No BBMR runner/acceptance process was active. Root `.env` changed only from `0644` to `0600`; regular-file owner/group/size stayed unchanged and contents were never read.
- **Lock Evidence**: Root `uv.lock` was generated from byte-identical `pyproject.toml` using the approved complete marker-aware preferences. NumPy is `2.4.6` only for Python `<3.12` and `2.5.0` for Python `>=3.12`; no `2.5.1`. Frozen Python 3.12 sync selected `2.5.0`; `uv lock --check`, `git diff --check`, and 453 Python tests passed. Cache: `/private/tmp/bbmr-audit-g6-uv-cache.rayS3d`; environment: `/private/tmp/bbmr-audit-g6-uv.BVluwE`.
- **Frontend Boundary Evidence**: Moved only `frontend/.git` to `/Users/jeffrey/Documents/布林带策略_frontend_git_backup_2026-07-20`. Backup remains unborn `main` with no commit; 60 frontend source files retained the same digest; parent has no gitlink and tracked diff/index/HEAD/branch/remotes/staged set were unchanged.
- **Planning Read-Only Check**: Confirmed `.env` mode `0600` without reading contents, lock markers/no `2.5.1`, both temporary paths, absent `frontend/.git`, valid backup symbolic ref, unchanged `pyproject.toml`, empty staged diff, and successful `uv lock --check`.
- **Scope Skipped**: No source/test/YAML/frontend-source/docs/repository-venv/Git-index/commit/runner/exchange/live-DB/mainnet/G7 action. Maintenance did not self-accept.
- **Recovery Command Not Run**: `mv "/Users/jeffrey/Documents/布林带策略_frontend_git_backup_2026-07-20" "/Users/jeffrey/Documents/布林带策略/frontend/.git"`
- **Acceptance**: 完成了执行和验收，进入下一步

### 2026-07-20 - AUDIT-G4 Stop Protection Truth Execution
- **Status**: Completed; independent Acceptance passed
- **Zone**: Execution
- **Description**: Added exchange-verified stop truth, durable deterministic replacement intents, restart-safe unknown/create/cancel recovery, and account-wide entry blocking while protection is unresolved.
- **Evidence**: Temporary-store/fake-exchange regressions cover invalid stop fields, timeout preservation, lost create response, cancel-pending restart convergence, configuration fail-closed, and dashboard recovery projection. No real database, runner, exchange, YAML, frontend, mainnet, or Git write was used.
- **Changed**: `src/bbmr/live/{config,hyperliquid_client,state_store,trailing_runtime,run,dashboard}.py`, focused live tests, strategy consensus, and ADR-011.
- **Rework**: Acceptance rework closes ambiguous-create resubmission: a persisted `create_attempted` marker is committed before the only create request, so later missing/unknown client-ID lookups remain recovery and never submit another stop. Added server-canceled/response-lost restart convergence and update/promotion event-rollback regressions.
- **Acceptance**: 完成了执行和验收，进入下一步

### 2026-07-20 - AUDIT-G5 MR Entry Idempotency And Account Reservation Execution
- **Status**: Completed; independent Acceptance passed
- **Zone**: Execution
- **Evidence**: Durable MR intent uses bound account/symbol/side/setup/5m identity and a deterministic client ID. Intent and submit-attempt persist before the single IOC call; unknown results reconcile only. Non-terminal MR/live-trend reservations and strictly parsed manual entry orders are included in notional/margin budgets; malformed account-order truth blocks entries without mutation. Post-mutation account refresh failure blocks later symbols for that poll.
- **Changed**: `src/bbmr/live/{hyperliquid_client,state_store,trailing_runtime,run}.py`, focused live tests, strategy consensus, and ADR-012.
- **Verified**: Temporary SQLite/fake exchange tests cover persistence failure before order calls, response loss across restart, actual partial-fill recovery into protection, terminal no-fill trigger consumption, deterministic IDs, reservation classification, and cross-symbol refresh failure blocking. No real database, runner, exchange, YAML, frontend, mainnet, or Git write was used.
- **Acceptance**: 完成了执行和验收，进入下一步

Read this summary first, then only the latest entry relevant to the current task. Historical entries below remain append-only context.

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

### 2026-07-18 - Frontend Flow Condition/Action Shapes
- **Status**: Completed
- **Zone**: Execution
- **Description**: Kept trigger conditions as rounded rectangles and rendered post-trigger protection, target, and close actions as the existing capsule confirmation shape in both live and archived flow charts.
- **Changed**: `frontend/app/flow-data.ts`, `frontend/app/page.tsx`, `frontend/app/archive/[id]/page.tsx`, and `frontend/tests/rendered-html.test.mjs`.
- **Verified**: `cd frontend && npm test` passed: build completed and 3/3 tests passed.
- **Scope Skipped**: Strategy/runtime/API/SQLite/archive generation, runner control, Git, and dependencies.
- **Follow-up**: The live card now separates backend-owned long and short `slow_slope_state` values and labels the top badge as management status. The authorized read-only dashboard extension now exposes the completed 1h middle-band slow-slope ratio as `entry_risks.long/short.slow_slope_pct`; the UI prints the backend-supplied value next to each directional state. No frontend strategy computation was added. Focused dashboard tests passed 8/8; frontend tests passed 3/3. Existing running local Python processes must be restarted manually before a new snapshot/API response contains this new field.

### 2026-07-20 - Frontend Live Flow Payload Order Tolerance
- **Status**: Completed
- **Zone**: Execution
- **Description**: Restored live rendering when the backend sends the valid entry flow in evaluation order rather than the frontend's visual order.
- **Changed**: `frontend/app/page.tsx`, its local read-only route aliases under `frontend/app/dashboard/`, archive request paths, `frontend/tests/rendered-html.test.mjs`, and this worklog/bug log.
- **Evidence**: The local snapshot and `:8765` / `:3000` APIs were fresh; Chrome reproduced the empty fallback. After accepting known entry node/connector sets independent of transport order, Chrome displayed `运行中`, BTC steps, directional slope, BandWidth data, and current poll messages. `cd frontend && npm test` passed: build and 3/3 tests.
- **Scope Skipped**: No trading strategy/runtime, order path, runner control, YAML, SQLite, dependency, or Git change.

### 2026-07-17 - Zone-Memory Workflow Resync
- **Status**: Completed
- **Zone**: Planning
- **Description**: Synchronized the existing four-zone workflow to the ultra-lean zone-memory rules without creating new zones or an active task file.
- **Changed**: `AGENTS.md`, `docs/project_notes/zone_operating_model.md`, `docs/project_notes/key_facts.md`, `docs/project_notes/issues.md`, and workflow ADR-004 in `docs/project_notes/decisions.md`.
- **Verified**: Targeted reads and targeted diffs; `git status --short`; confirmed `docs/project_notes/current_task.md` remains absent.
- **Scope Skipped**: Production strategy code, tests, YAML, frontend, runner control, exchange writes, Git writes, mainnet, and strategy-consensus content.
- **Notes**: Acceptance remains independent and fully read-only. Planning or Execution records its verdict verbatim after receipt. No Execution or Acceptance task is active or required for this low-risk documentation resync.

### 2026-07-20 - STRATEGY-14 Mean-Reversion 5m Trigger Before BandWidth Final Authorization
- **Status**: Execution completed; independent Acceptance pending
- **Zone**: Execution
- **Description**: Moved only the mean-reversion BandWidth/linkage allow decision behind the existing completed-5m previous-extreme/no-chase production trigger. Shared completed-1h entry risk still determines setup RSI, effective state, and selected leverage before confirmation.
- **Evidence**: A blocked 5m trigger records the existing `bandwidth_entry_blocked` event with setup identity, side, completed-5m bucket/close, linkage/source/age, and reason; it creates no leverage, market-entry, or stop write. The persisted event also prevents a recovered guard from opening on that old 5m trigger; a new trigger remains eligible. Shadow trigger recording remains before final authorization.
- **Dashboard**: Backend/API and frontend reuse the existing nodes in the order `1h setup/RSI -> completed 5m -> previous-extreme break -> BandWidth -> account/orderbook -> protected open`.
- **Verified**: `./.venv/bin/python -m pytest tests/live/test_trailing_runtime.py tests/live/test_dashboard.py tests/live/test_trailing_helpers.py -q`; `npm test` in `frontend/`; `./.venv/bin/python -m pytest tests -q` all passed.
- **Scope Skipped**: BandWidth formulas/thresholds/linkage semantics, YAML/schema/SQLite schema, trend riding, position management, sizing/leverage rules, stop/TP, runner control, exchange writes, mainnet, and Git operations.
- **Rework 1 Evidence**: Moved exchange-position and exchange-open-order guards after completed-5m trigger, final BandWidth/linkage authorization, historical blocked-trigger check, and non-EXSPECIAL slope check, while retaining their position before balance, account-cap, order-book, leverage, and order paths. New regressions prove no-trigger and BandWidth-blocked paths make zero position/open-order/quote guard calls, while allowed triggers still stop at an existing exchange position or open order.
- **Rework 1 Verified**: `./.venv/bin/python -m pytest tests/live/test_trailing_runtime.py tests/live/test_live_run.py -q` and `./.venv/bin/python -m pytest tests -q` passed. No dashboard/frontend/consensus/YAML/schema changes were made.

### 2026-07-20 - AUDIT-G1 Account and Position Truth
- **Status**: Execution completed; independent Acceptance required
- **Zone**: Execution
- **Description**: Hyperliquid Standard/cross account facts now use CCXT `USDC.total` exactly once and `min(valid free, valid raw withdrawable)` for available margin. Position parsing accepts only validated `contracts`, `long`/`short`, and `positionValue`/`notional` or `qty * markPrice`; malformed data stops the poll before reconcile, cancel/archive, leverage, or order paths.
- **Changed**: `src/bbmr/live/hyperliquid_client.py`, `src/bbmr/live/trailing_runtime.py`, `tests/live/test_hyperliquid_client.py`, `tests/live/test_trailing_runtime.py`, `tests/live/test_live_run.py`, and `docs/strategy_consensus/bbmr_trailing_stop_v1.md`.
- **Verified**: `./.venv/bin/python -m pytest tests/live/test_hyperliquid_client.py tests/live/test_trailing_runtime.py tests/live/test_live_run.py -q` and `./.venv/bin/python -m pytest tests -q` passed.
- **Scope Skipped**: Strategy formulas, YAML, frontend, runner control, exchange writes, mainnet, Git, lifecycle P2-04, and other audit goals.

### 2026-07-20 - AUDIT-G2 Exchange Submission Boundary
- **Status**: Completed; independent Acceptance passed
- **Zone**: Execution
- **Description**: The fixed CCXT instance now disables builder fee/referrer initialization. A mean-reversion entry reuses one approved L2 snapshot to submit exactly one side-aware IOC limit inside the configured 100 bps boundary; no ticker-last read, L2 refetch, reprice, or widened retry occurs.
- **Evidence**: A no-network current-pin CCXT spy invokes production `_create_exchange()` and `create_ioc_entry()` with fake market/signature/private transport. It records no `approveBuilderFee` or `setReferrer` action, no `builder` in either final action, and long/short `Ioc` prices inside their `1.01`/`0.99` envelopes. Runtime regression proves one quote probe is passed by identity to submission; an unconfirmed IOC does not retry or create a local open trade. Existing post-fill warning and protection regression remains covered.
- **Changed**: `src/bbmr/live/hyperliquid_client.py`, `src/bbmr/live/trailing_runtime.py`, `tests/live/test_hyperliquid_client.py`, `tests/live/test_trailing_runtime.py`, `docs/strategy_consensus/bbmr_trailing_stop_v1.md`, and ADR-009 in `docs/project_notes/decisions.md`.
- **Verified**: `./.venv/bin/python -m pytest tests/live/test_hyperliquid_client.py tests/live/test_trailing_runtime.py tests/live/test_live_run.py -q` and `./.venv/bin/python -m pytest tests -q` passed.
- **Acceptance**: 验收通过，进入下一步。
- **Scope Skipped**: Existing account attribution revocation, YAML/default slippage, stop/close/manual adoption/Trend GTC behavior, durable MR intent/idempotency, frontend, runner control, exchange writes, mainnet, Git, and other audit goals.

### 2026-07-20 - AUDIT-G3 Runtime Identity And Persistence Foundation
- **Status**: Planned; ready for manual Execution handoff
- **Zone**: Planning
- **Description**: Bind runner and persistence identity to an irreversible environment-plus-wallet fingerprint, reject duplicate/equivalent symbols and duplicate active trades, and make funds-critical state/event writes atomic before later stop and entry recovery Goals.
- **User Decision**: Preserve the existing non-empty testnet SQLite database and require an explicit first-time binding after read-only verification; do not replace or delete it.
- **Routing**: Automation is disabled. The user manually forwards the Planning task card, Execution evidence, Acceptance card, and any rework card under the local zone rules.
- **Scope Boundary**: No current live-DB mutation during implementation or Acceptance, no runner/exchange/Git operation, and no stop-recovery, MR-intent, operational-governance, or Ponytail work.

### 2026-07-20 - AUDIT-G3 Runtime Identity And Persistence Foundation Execution
- **Status**: Completed; independent Acceptance passed
- **Zone**: Execution
- **Description**: Canonicalized configured/CLI symbols, bound runner identity to a one-way environment-plus-wallet fingerprint, and acquired the independent identity lock before the existing SQLite liveness lock and store open.
- **Evidence**: New stores bind automatically; non-empty legacy stores require `--bind-legacy-identity` and reject active trades/non-terminal pending orders; mismatches fail before client construction. SQLite enforces one active `exchange_position_key`. Entry/recovery, adoption/size, stop, and archive lifecycle writes now pair local state with their journal event atomically; exchange calls remain outside transactions.
- **Verified**: `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest -p no:cacheprovider tests/live/test_live_config.py tests/live/test_state_store.py tests/live/test_trailing_runtime.py tests/live/test_live_run.py -q`, `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest -p no:cacheprovider tests -q`, and `git diff --check` passed. Ponytail review: `Lean already. Ship.`
- **Scope Skipped**: No YAML, frontend, runner start/stop, real exchange/private API, real SQLite mutation, strategy/sizing/stop formula, mainnet/trend state, or Git operation.
- **Rework Evidence**: Explicit `--symbol ""` now reaches canonical validation and fails before store/client construction; canonical CLI aliases remain accepted.
- **Acceptance**: 已完成验收，进入下一步。

### 2026-07-20 - AUDIT-G4 Stop Protection Truth
- **Status**: Planned; complex handoff ready for manual initial transfer
- **Zone**: Planning
- **Description**: Verify protective-stop exchange truth on every managed full poll and add durable, restart-safe replacement recovery without changing stop formulas or position-management regimes.
- **Handoff**: `/private/tmp/bbmr_audit_g4_stop_protection_handoff_2026-07-20.md`
- **Routing**: The user manually starts Execution. Execution then routes evidence plus the Planning-authored Acceptance Contract directly to Acceptance; Acceptance routes rework directly to Execution or sends the exact pass message to Planning.
- **Scope Boundary**: P1-04/P1-05/P1-07 only; no G5 idempotency, G6 operations, G7 cleanup, YAML, frontend, real DB, runner/exchange/mainnet, or Git writes.

### 2026-07-20 - AUDIT-G5 MR Entry Idempotency And Account Reservation
- **Status**: Planned; complex handoff ready for manual initial transfer
- **Zone**: Planning
- **Description**: Persist one deterministic MR intent per completed-5m trigger, reconcile ambiguous outcomes without resubmission, and enforce fresh account-wide notional/margin reservations across symbols and open orders.
- **Handoff**: `/private/tmp/bbmr_audit_g5_entry_idempotency_budget_handoff_2026-07-20.md`
- **User Decisions**: One trigger submits at most once; non-terminal MR/live-trend rows reserve funds without double counting positions; unknown manual orders are never canceled and unverifiable exposure blocks every new strategy entry.
- **Routing**: The user manually starts Execution. Execution routes evidence plus the Planning-authored Acceptance Contract directly to Acceptance; Acceptance routes rework directly to Execution or sends the exact pass message to Planning.
- **Scope Boundary**: P1-03/P1-06 only; no G6 operations, G7 cleanup, strategy/YAML/frontend, real DB, runner/exchange/mainnet, or Git writes.

### 2026-07-20 - AUDIT-G6 Operational And Runtime Governance
- **Status**: Completed; implementation, Maintenance closeout, and final independent Acceptance passed
- **Zone**: Planning
- **Description**: Isolate dry-run persistence, preserve pending setups across transport failures, make fatal lifecycle durable and sanitized, harden testnet acceptance cleanup, require exact-or-unknown PnL, and move dashboard truth/configured symbols to runner-owned evidence.
- **Handoff**: `/private/tmp/bbmr_audit_g6_operational_governance_handoff_2026-07-20.md`
- **User Decisions**: Automatic separate dry-run SQLite; transport retry versus fatal fail-closed classification; zero confirmed before owned-stop cancellation; exact close identity/quantity or unknown PnL; later `.env` 0600 and `uv.lock`; parent-owned frontend with runner-authoritative decision trace.
- **Phases**: `AUDIT-G6-E` Execution plus independent implementation-gate Acceptance passed. `.env`, dependency lock, and `frontend/.git` now proceed through the separately transferred `AUDIT-G6-M` Maintenance handoff, followed by final read-only G6 closure. The implementation-gate pass does not authorize G7.
- **Maintenance Handoff**: `/private/tmp/bbmr_audit_g6_maintenance_closeout_handoff_2026-07-20.md`
- **Routing**: The user manually starts Execution. Execution routes evidence plus the Planning-authored implementation Acceptance Contract directly to Acceptance; Acceptance routes rework directly to Execution or sends the exact pass message to Planning.
- **Scope Boundary**: No strategy/YAML changes, real DB, runner/exchange/mainnet action, `.env` read/chmod, dependency/Git-metadata mutation during Execution, or G7 Ponytail cleanup.

### 2026-07-17 - STRATEGY-13 Frozen-Price EXSPECIAL Trend Entry Replacement
- **Status**: Completed
- **Zone**: Execution
- **Description**: Replace the accepted STRATEGY-11 trend-entry candidate/near-middle/5m-rebreak path with the newly approved one-shot canonical-EXSPECIAL frozen-close pullback order, while preserving the isolated trend-position management and safety chain.
- **Scope**: Backend strategy/config/runtime/persistence/client tests and strategy consensus only. No frontend, Git, mainnet activation, or runner-control changes. Active mode remains `shadow`.
- **Constraints**: Remove obsolete momentum, near-middle, and 5m-rebreak entry behavior rather than retaining compatibility branches. BandWidth remains mean-reversion-only evidence and cannot authorize or veto the new trend entry.
- **Documentation**: Active consensus defines the canonical first-EXSPECIAL episode, frozen `F`/fixed GTC `L`, one-attempt lock, late-start no-backfill rule, shadow completed-5m touch model, live fill/partial-fill priority, cancel conditions, clear YAML names, and unchanged isolated trend management. ADR-008 supersedes ADR-007's entry portion while preserving its three-state mode, isolation, and shadow-comparison decisions.
- **Acceptance**: Passed on the third independent read-only review. Evidence: runtime `111/111`, full suite `375/375`, and `git diff --check` passed; active mode remains `shadow`. No frontend changes, runner start, exchange writes, Git operations, or mainnet actions were performed.

### 2026-07-15 - STRATEGY-12 BandWidth–Slope Entry-Risk Linkage Handoff
- **Status**: Completed
- **Zone**: Execution
- **Description**: Implement the agreed direct-testnet mean-reversion entry guard that combines immediate directional BandWidth shocks with short completed-1h middle-direction continuation while preserving canonical slow-slope and open-position management behavior.
- **Handoff**: `/private/tmp/bbmr_bandwidth_slope_linkage_execution.md`, `/private/tmp/bbmr_bandwidth_slope_linkage_acceptance.md`
- **Notes**: Implemented the shared completed-1h entry-risk helper across setup RSI, runtime pre-order block, leverage, terminal/journal evidence, and backend dashboard/API state. `BW_SHOCK_BLOCK` covers matching directional H0 shocks; `BW_CONTINUATION_SPECIAL` applies only through H1/H2 with strict middle continuity. Terminal/event/API units now distinguish ratio, percentile rank, and relative change. No YAML, SQLite, frontend, open-position, trend-riding, runner-control, or Git changes. Focused and full tests are recorded in the Execution report; the historical ETH values are covered by the shared calculation regression.
- **Follow-up**: Acceptance rework completed: each once-per-bucket observation now serializes the shared long/short entry-risk results, including linkage, source bucket, age, strict RSI threshold, selected leverage, and effective state. Terminal and dashboard/API reuse those fields; old payloads retain unavailable defaults.
- **Follow-up**: Ownership corrected by user: production strategy/runtime implementation belongs to Execution Zone. The frontend window was stopped after an incomplete partial edit to `src/bbmr/trailing.py`, `tests/live/test_trailing_helpers.py`, and this worklog; Execution must inspect and safely take over that diff. This backend batch excludes `frontend/`. A later frontend-only task may format authoritative dashboard/API fields but may not modify production strategy/runtime behavior or backend strategy tests.
- **Follow-up**: Backend implementation passed independent Acceptance after one rework: per-bucket terminal/journal/dashboard observations now reuse the same side-specific `entry_risk_state` for H1/H2 and expose long/short linkage, source bucket, age, RSI threshold, leverage, and effective entry risk while preserving event dedupe and old-payload defaults. The subsequent frontend-only display slice changed only `frontend/app/flow-data.ts`, `frontend/app/page.tsx`, `frontend/app/globals.css`, and `frontend/tests/rendered-html.test.mjs`; it formats raw BandWidth as percent, percentile as `/100`, relative changes as percent, and renders backend-provided long/short entry risks without strategy inference. Final frontend Acceptance passed after a minimal P2 rework made H0/H1/H2 all render backend-provided source bucket and age. Frontend `npm test` passed 3/3 and lint had no errors (the existing archive `<img>` warning remains). Trend riding remains a separate deferred topic.
- **Follow-up**: Terminal output no longer prints BandWidth observations; the once-per-bucket SQLite journal and backend dashboard evidence remain active.

### 2026-07-15 - STRATEGY-11 EXSPECIAL Directional Trend-Ride Discussion
- **Status**: Completed; independent Acceptance passed
- **Zone**: Planning
- **Description**: Evaluate a separate trend-pullback entry path that follows an extreme completed-1h slope instead of taking the blocked adverse mean-reversion side.
- **Handoff**: `/private/tmp/bbmr_trend_riding_execution.md`, `/private/tmp/bbmr_trend_riding_acceptance.md`
- **Notes**: User approved direct testnet implementation without a shadow phase, but requested final discussion of slope lag and stale sideways entries before task assignment. Read-only ETH testnet reproduction at 2026-07-15 04:49 UTC found completed-1h middle slope `+0.7872%` while 3h close momentum was `-0.2704%`, BandWidth contracted `-9.9908%`, and the last upper-band touch was 12 completed hours old; the proposed 25% near-middle zone already contained the latest completed 5m close. Changing the existing middle-band `slope_n` alone does not solve this: the same stale bucket measured `+0.5200%` at `n=2` and `+0.2569%` at `n=1`, both still EXSPECIAL at the current `0.25%` threshold, while `n=1` would have detected the original impulse one completed hour later. Planning therefore preserves `slope_n=3` for established NORMAL/SPECIAL/EXSPECIAL risk routing and evaluates the BandWidth-plus-directional-continuity bridge below. Exact combined entry contract remains to be confirmed; no strategy implementation task has been issued yet.
- **Execution**: Delivered YAML `trend_riding.mode: shadow` (schema default `off`) and `execution.trend_riding_leverage: 2`; changed `configs/strategy_bbmr_trailing_stop_v1.yaml`, `configs/live_hyperliquid_testnet.yaml`, `src/bbmr/config.py`, `src/bbmr/trailing.py`, `src/bbmr/live/config.py`, `src/bbmr/live/state_store.py`, `src/bbmr/live/trailing_runtime.py`, `src/bbmr/live/run.py`, and `src/bbmr/live/dashboard.py`. Added restart-safe additive SQLite trend-shadow table/event linkage, pure completed-candle trend candidate/rebreak helpers, shadow lifecycle and backend observation, 5m-aligned candidate scheduling, source-routed live trend opening/management, and adverse-MR live blocking. Active mode is `shadow`; it creates no exchange mutation, and `off` bypasses new trend creation. Existing focused suite passed (230 tests) and full suite passed (309 tests). Frontend, Git, mainnet, and runner controls were untouched. Manual runtime observation and independent Acceptance remain required.
- **Rework**: Acceptance P0 fixed in `src/bbmr/live/trailing_runtime.py`: the `trend_would_block_mean_reversion` observation now passes both `balance` and `exchange_positions` to `_trend_payload`, so valid shadow/live candidates no longer raise `TypeError`. The new direct shadow-path regression in `tests/live/test_trailing_runtime.py` reaches a valid long candidate/rebreak, asserts candidate/block/open events plus the persisted simulated position, and proves `set_leverage`, market entry, stop creation, cancellation, and close calls all remain zero. It also exposed and corrected the matching SQLite insert placeholder count in `src/bbmr/live/state_store.py`. Focused required suite passed (231 tests); full suite passed (310 tests). Frontend, Git, mainnet, and runner controls remain untouched; independent Acceptance is still required.
- **Rework 2**: Acceptance P0 completed without expanding strategy scope. Candidate/open snapshots now freeze the contemporaneous local managed trade (source/side/qty/entry/current stop/management state), pending mean-reversion stage plus allow/block result, existing long/short entry-risk evidence (including BandWidth base/H0-H2 linkage), trend gate pass/fail, and immutable YAML taker-fee/slippage assumptions. Every simulated stop, NORMAL fallback, and weakening-middle-cross close now saves a time-window query of overlapping `live_trades` with ID/status/source/close reason/PnL/fees/provenance; open baselines are labeled `unresolved` and an empty list remains valid. Simulated costs use the frozen entry and exit notionals with frozen bps, and close events persist gross/cost/net values. Regression covers a current real local trade and pending MR decision, nonzero costs, resolved real PnL attribution, protective-stop closure, weakening active-exit closure, and zero exchange writes. Required focused suite passed (231 tests); full suite passed (310 tests). Frontend, Git, mainnet, active shadow YAML, and runner controls remain untouched; independent Acceptance remains required.
- **Rework 3**: Acceptance P0 completed with one localized real-trend stop safety guard. Before replacing a tightened trend stop, the runtime fetches the latest mark; an already-crossed long/short stop now uses the existing market-close and zero-position verification flow instead of submitting a crossed stop. The old reduce-only stop and local record remain unchanged until zero position is verified; close submission or verification failures retain them, emit `trend_market_close_failed` at CRITICAL severity, and retry on a later completed bucket. Long/short successful crossed-stop and close/verification-failure regressions passed. Required focused suite passed (235 tests); full suite passed (314 tests). Shadow writes remain exchange-free; active YAML remains `shadow`; frontend, Git, mainnet, and runner controls were untouched. Independent Acceptance remains required.
- **Rework 4**: Acceptance P0 completed with a localized real-trend post-submit confirmation boundary. `set_leverage` and market-order submission failures remain pre-submit failures; once `create_market_entry` returns, any position-confirmation exception or missing position creates a `source=trend_riding`, `entry_unprotected` recovery record with expected side/quantity, entry time, order anchor, reason, missing-protection state, and CRITICAL journal evidence. This local state blocks duplicate trend entry for that symbol. Existing reconcile then either confirms the exchange position, installs protection, and journals recovered open state, or confirms no position and safely archives the unresolved local record without guessing a fill. Regression covers submitted-entry confirmation timeout, duplicate blocking, recovered protection, and confirmed-no-position cleanup. Required focused suite passed (236 tests); full suite passed (315 tests). Shadow writes remain exchange-free; active YAML remains `shadow`; frontend, Git, mainnet, and runner controls were untouched. Independent Acceptance remains required.
- **Rework 5**: Contract-closure fixes kept localized. Invalid/short completed-5m input now clears stale trend candidate/gates; pure rebreak rejects equal or reverse candle completion times; candidate/shadow watch scheduling remains aligned to completed-5m plus grace instead of 30-second full OHLCV. A market-entry exception is now treated as ambiguous and persists the same CRITICAL trend recovery record. Invalid trend slope preserves existing live trend state. Candidate snapshots include exchange/local baseline, conflicting-order and generic safety evidence, side-specific MR risk/BandWidth linkage, frozen taker-cost provenance, and an append-only actual-MR outcome after the real MR decision. Shadow replay consumes missed completed rows in timestamp order; backend trend observation exposes independent real lane and shadow stop/BE/phase/baseline-clean/PnL fields. Active YAML now freezes testnet costs at taker `4.5` bps, maker `1.5` bps, and explicit zero additional slippage; production archive writes exit time and overlap queries exclude closed history outside the interval. Required focused suite passed (236 tests); full suite passed (315 tests). Frontend, Git, mainnet, and runner controls remain untouched; independent Acceptance remains required.
- **Rework 6**: Final MR outcome is stored on the open shadow row (not treated as entry-time fact) and is exposed through backend trend observation; close snapshots retain the immutable signal snapshot, stored MR result, current local baseline, and overlapping real trade attribution. Shadow replay now scans all missed completed 5m/1h buckets after persisted markers, with 5m stop handling before 1h management for each available progression. Real trend zero-position stop-cancel failures now enter CRITICAL `exit_cleanup` retry state, which retries cancellation only before archive. Direct regressions add equal-time rebreak rejection and NaN/positive-infinity/negative-infinity trend-slope state preservation. Required focused suite passed (240 tests); full suite passed (319 tests). Active YAML remains shadow with taker `4.5`/maker `1.5` bps and zero extra slippage; shadow remains exchange-write-free; frontend, Git, mainnet, and runner controls remain untouched. Independent Acceptance remains required.
- **Rework 7**: Real trend orders now reuse the established pre-entry top-book reference, order-fill price extraction, `max_entry_slippage_bps` comparison, and `entry_slippage_exceeded` payload/event chain. A warning is journaled only after a confirmed fill and local trend recovery record exists; exceeding the threshold never cancels, reverses, or duplicates the filled order, and normal stop installation/management continues. Direct trend regressions cover over-threshold warning plus protected `source=trend_riding` state, in-threshold non-warning, and no fabricated fill-slippage event on ambiguous confirmation. Required focused suite passed (242 tests); full suite passed (321 tests). Active YAML remains shadow; frontend, Git, mainnet, and runner controls remain untouched. Independent Acceptance remains required.
- **Rework 8**: Backend snapshot now routes an open `source=trend_riding` trade before MR management rendering. It emits an explicit `trend_riding` management lane with protective stop, water mark, break-even, weakening, middle-cross, NORMAL fallback, and exit-cleanup states; top-level MR branch connectors, MR management steps/connectors, and MR summary are absent. Strategy and manual-adopted snapshot behavior remains unchanged. Added a direct dashboard regression asserting the isolated trend lane. Required focused suite passed (243 tests); full suite passed (322 tests). Frontend, Git, mainnet, config, and runner controls remain untouched; independent Acceptance remains required.
- **Acceptance**: Independent read-only Acceptance passed after Rework 8 with `STRATEGY-11_ACCEPTANCE_PASS`. The active rollout remains `trend_riding.mode: shadow`; shadow creates no exchange writes, and promotion to `live` remains a later explicit YAML decision after sufficient comparison data is reviewed.
- **Follow-up**: The independent fast-slope severity overlay is rejected after testing the user's oscillation concern. Across 361 comparable completed-1h rows per BTC/ETH/SOL, a normalized one-hour middle-slope threshold fired while slow slope remained NORMAL in `6.9%-7.5%` of rows; `18.5%-38.5%` of those alerts did not become same-direction slow SPECIAL within three hours. Slow `slope_n=3` remains the canonical NORMAL/SPECIAL/EXSPECIAL classifier and open-position management authority.
- **Follow-up**: A directional low-base BandWidth shock is a stronger early bridge. Among 19 completed-1h outer-band closes with `BandWidth change_1h >=10%` while slow slope was NORMAL, 18 later became same-direction slow SPECIAL: 12 after one hour, five after two, and one after three. All 18 kept every one-hour middle increment in the shock direction until slow classification took over; the sole unconfirmed ETH candidate reversed its middle increment on the third step. Current proposal: block the adverse mean-reversion side in the shock bucket, then apply only a temporary SPECIAL entry floor while all subsequent completed-1h middle increments remain in the shock direction, for at most the next two buckets; cancel immediately on reversal, and let slow state take over thereafter. Derive this from the recent completed rows without a new persisted state. BandWidth alone must not authorize trend riding or alter open-position management.
- **Follow-up**: The user's ETH screenshot at the `2026-07-14 20:00 Asia/Shanghai` candle was aligned to testnet data. BandWidth rose from `2.848476%` to `4.806455%`, a relative one-hour expansion of `68.737776%`; its 120h percentile was `100`, close `1862.2` was above upper band `1829.2442`, RSI14 was `77.579563`, and slow short-side slope was EXSPECIAL at `+0.364643%`. The setup would therefore be independently blocked by both the already accepted `HIGH_EXPANDING` guard and EXSPECIAL slope; the proposed low-base directional-shock extension does not change this particular outcome.
- **Follow-up**: Trend-riding design and implementation are explicitly deferred until `STRATEGY-12` is implemented and independently accepted; no trend-riding behavior belongs in that task.
- **Follow-up**: User confirmed the trend-ride exit contract: leaving directional EXSPECIAL creates a weakening warning rather than an immediate close; while warned, the first completed 1h close crossing the completed 1h middle against the position triggers a market close; a return to EXSPECIAL before that crossing clears the warning; slow slope returning to NORMAL remains the fallback close. The exchange protective stop remains active throughout. Entry confirmation and trend-specific trailing behavior are still under discussion; no implementation task has been issued.
- **Follow-up**: User confirmed trend-ride management isolation: trend positions do not reuse the current NORMAL staged stop chain, SPECIAL rolling-middle take-profit, EXSPECIAL defensive exit, or the earlier midband-follow proposal. A separate exchange protective-stop lane handles catastrophic risk, while the active trend exit remains the confirmed weakening / completed-1h middle-cross / slow-NORMAL fallback contract. Initial protective-stop placement and movement remain unresolved; no implementation task has been issued.
- **Follow-up**: User confirmed the trend-ride initial protective stop. Freeze the entry-time completed-1h bands and use the closer of structural invalidation and the existing 5% price-distance cap: long `max(entry_price * 0.95, completed_1h_lower)`; short `min(entry_price * 1.05, completed_1h_upper)`. The protective stop may only tighten after entry and must never be loosened. Its later tightening trigger remains under discussion; no implementation task has been issued.
- **Follow-up**: User subsequently revised and superseded that initial-stop formula for trend rides. Initial stop is exactly `entry_price * 0.95` for a long and `entry_price * 1.05` for a short; the entry-time opposite outer band is no longer an initial-stop candidate. After entry, evaluate only completed `1h` closes: long stop candidate is `highest_post_entry_completed_1h_close * 0.95`, short candidate is `lowest_post_entry_completed_1h_close * 1.05`. The exchange stop is monotonic, may pass the entry price to lock profit, and therefore has execution priority over the separate weakening / 1h-middle-cross / slow-NORMAL active exit chain if hit first. The one-time favorable-outer-band break-even candidate remains agreed in principle, but its completed-candle trigger basis is still to be confirmed; no implementation task has been issued.
- **Follow-up**: User confirmed the one-time favorable-outer-band break-even trigger also uses completed `1h` closes: long when the first post-entry completed `1h close >= that row's upper band`; short when the first post-entry completed `1h close <= that row's lower band`. Once triggered, entry price remains a permanent stop candidate. Intrabar or candle-wick touches do not trigger this rule. Gap handling for a newly calculated stop that is already crossed at replacement time remains under discussion; no implementation task has been issued.
- **Follow-up**: User confirmed trend-stop gap handling. Before replacing the exchange stop, compare the newly calculated trigger with a fresh mark price. If a long's new stop is already at or above mark, or a short's is already at or below mark, treat the hourly trailing stop as already crossed and immediately request a market close. Keep the previous reduce-only protective stop until exchange position closure is verified; if the market close or verification fails, retain that old stop, retry through the existing recovery path, and emit a high-severity alert. Do not clamp the new stop near market and do not wait for price to recover. No implementation task has been issued.
- **Follow-up**: User rejected the earlier proposal that a recent BandWidth shock be a positive prerequisite for trend riding; that unconfirmed H0-H2 impulse-TTL proposal is withdrawn. The intended opportunity is a gradual fresh slow-slope transition into directional EXSPECIAL while price remains on the trend side and BandWidth is comparatively stable. BandWidth should act only as a veto for shock-driven lag, not as entry authorization. Read-only replay aligned the user's SOL cursor (`2026-07-13 14:00 Asia/Shanghai` label) at `slope3=-0.105244%` SPECIAL and `BandWidth change_1h=+3.023983%`; the first subsequent downward EXSPECIAL row was the `20:00` label at `slope3=-0.258731%`, with three strictly falling middle increments, `3h close momentum=-1.047936%`, close below middle, and `BandWidth change_1h=+0.261739%`. By contrast, the ETH shock case first entered upward EXSPECIAL with same-hour BandWidth expansion `+68.737776%` (and another `+13.326878%` shock within the preceding three rows). Current minimal proposal is therefore a fresh directional EXSPECIAL cycle after a NORMAL reset, three same-direction middle increments, same-direction 3h close momentum, current close on the trend side of middle, and no `BandWidth change_1h >=10%` in the latest three completed 1h rows. Whether trend entry must wait for actual EXSPECIAL or may use a SPECIAL early-warning state remains to be confirmed; no implementation task has been issued.
- **Follow-up**: User confirmed a Ponytail simplification that supersedes the extra trend-entry state proposed immediately above. Trend authorization now has only four gates: the current completed-1h slope reaches the agreed directional trend threshold; completed-1h 3h close momentum has the same sign; price returns to the agreed 25% near-middle zone (long: middle through the inner 25% toward upper, short: middle through the inner 25% toward lower); and a later completed-5m close rebreaks the previous completed-5m high for long or low for short. A prior NORMAL reset, three consecutive middle increments, recent BandWidth-shock TTL, and shock-history veto are removed from the trend path. STRATEGY-12 remains an independent adverse mean-reversion brake, not a positive trend-entry prerequisite. The exact trend slope threshold, and whether lowering it should be trend-only or should change canonical EXSPECIAL globally, remain under discussion; no implementation task has been issued.
- **Follow-up**: User proposed replacing the trend candidate's 3h middle slope with a 2h middle slope. A read-only BTC/ETH/SOL comparison across 14,931 completed 1h rows found that the empirically equivalent `2h >= 0.14%` candidate had essentially the same six-hour progression to canonical `3h >= 0.25%` as `3h >= 0.18%` (`73.1%` versus `73.4%`) and the same 17 independent short-window 5m opportunities, but did not improve average lead time (`0.87h` versus `0.91h`) and fell back below its own threshold more often within six hours (`58.6%` versus `48.3%`). Faster `2h >= 0.10%` increased opportunity count but reduced six-hour progression to `55.5%` and increased six-hour opposite-direction flips to `13.8%`. Current Planning recommendation is therefore to keep canonical risk classification at `slope_n=3` and use a trend-only `3h >= 0.18%` candidate with the already agreed same-direction 3h close momentum, 25% near-middle zone, and later completed-5m rebreak. The historical progression percentages are calibration proxies, not profit or loss rates. No implementation task has been issued and no YAML or production behavior has changed.
- **Follow-up**: User confirmed the slope-window decision. Trend riding uses the existing completed-1h middle data with a trend-only three-hour slope threshold of `0.0018` (`0.18%`), while the canonical NORMAL/SPECIAL/EXSPECIAL classifier remains `slope_n=3` with existing `0.0009` and `0.0025` boundaries. No 2h trend overlay or global `slope_n` change will be introduced. In the trend lane, falling below the directional `0.18%` qualification creates the previously agreed weakening warning and recovering to it clears that warning before a middle-cross exit; the canonical return to NORMAL remains the fallback exit. Position sizing and leverage for a newly opened trend ride remain unresolved; no implementation task has been issued and no YAML or production behavior has changed.
- **Follow-up**: User confirmed trend-ride sizing. Reuse the current `execution.margin_fraction = 0.15` and total-notional cap, but add an independently named trend leverage authority of `2x`; a new trend ride therefore targets notional equal to `30%` of account equity. With the confirmed 5% entry-distance protective stop, the pre-cost initial loss at that stop is approximately `1.5%` of account equity. Do not couple this value to the existing mean-reversion `adverse_slope_leverage`, do not add to an existing strategy position, and keep the existing account-wide notional guard. No implementation task has been issued and no YAML or production behavior has changed.
- **Follow-up**: User confirmed directional conflict routing. When live trend mode has a valid up slope-plus-momentum candidate, block only a new adverse short mean-reversion order; a down candidate blocks only a new adverse long mean-reversion order. The trend order still waits for its near-middle and later completed-5m rebreak. Same-direction mean-reversion remains eligible until a position exists; a fully triggered trend order receives same-poll priority. Shadow mode records the counterfactual block but never changes the production setup or order path.
- **Follow-up**: User delegated the remaining trend-riding decisions to Planning and required YAML gating. Planning selected one three-state `trend_riding.mode = off | shadow | live`, with schema default `off` and first active YAML value `shadow`. `off` preserves the accepted current new-entry behavior; `shadow` uses the same evaluator but produces no exchange mutation or production block; `live` enables the directional block and separate trend order/management path. Mode only gates new creation: existing real trend positions and open simulated trend positions remain protected/updated to a terminal outcome in every mode. YAML changes take effect on runner restart, and pre-restart arms never promote into a live order.
- **Follow-up**: The final 5m trigger is stateless and completed-candle-only. Inside one current completed-1h candidate snapshot, the previous and current completed 5m closes must both be inside the inclusive 25% near-middle zone, both must complete after the candidate's 1h close, and the current close must strictly rebreak the previous high/low. This makes the previous candle the arm, requires the trigger candle to remain in-zone, resets naturally on zone exit or new completed-1h snapshot, and needs no pending-setup or arm persistence.
- **Follow-up**: BandWidth remains a veto, not trend authorization. The base valid/not-`HIGH_EXPANDING` guard applies to a new real trend order; the accepted H0/H1/H2 linkage remains mean-reversion-only and cannot create a trend candidate. Trend entries reuse generic equity, margin, account-notional, open-position/order, spread, slippage, fill-confirmation, protective-stop, and zero-position close guards.
- **Follow-up**: User required durable backend shadow comparison. Planning selected one dedicated SQLite trend-shadow trade table plus append-only state-change events, not the mean-reversion pending or short-horizon shadow tables. During active `shadow`, actual runner trades form the contemporaneous no-trend baseline while simulated trend trades persist entry evidence, observed executability, stop/weakening/exit state, MFE/MAE, simulated PnL provenance, and event/time anchors. Switching to `live` truncates the clean baseline marker; already-open simulations still finish and never become real orders. This is a labeled signal-level counterfactual, not a claim of exchange-fill accuracy or a fully isolated virtual account.
- **Follow-up**: User explicitly requires each shadow comparison sample to include the contemporaneous real trading baseline and filter evidence. Candidate/open/close snapshots must capture the exchange/local trade, source/side/quantity/entry/stop/management state, pending MR stage and actual allow/block decision; raw/percentile/change BandWidth plus base guard and H0/H1/H2 linkage; numeric canonical 3h slope and NORMAL/SPECIAL/EXSPECIAL/effective MR risk; numeric trend slope/momentum and threshold results. Shadow close must retain anchors and locally available overlapping actual-trade/PnL provenance; unresolved real trades remain labeled unresolved, and zero real trades is a valid baseline.
- **Follow-up**: Candidate/shadow observation will not force permanent 30-second full OHLCV polling. When a trend candidate or open shadow position requires 5m data, schedule full polls at completed-5m boundaries plus grace and reuse the existing frames. Read-only estimation is about `0.04%` of one CPU core and roughly `120` additional API calls per candidate-active hour for the current three-symbol shape, versus about `0.38%` core and roughly `1,300` avoidable extra calls per hour with naive 30-second full polling.

### 2026-07-14 - LIVE-RSI-1 Missing 5m RSI Shadow Column Crash
- **Status**: Completed
- **Zone**: Execution
- **Description**: Fixed the shadow-only 5m RSI feature contract without changing production entry logic or strategy parameters.
- **Handoff**: None
- **Notes**: The live builder now calculates configured 5m Wilder RSI from same-source completed OHLCV and requests `max(bb_period + 1, rsi.warmup_bars)` (500). Missing `rsi14` safely suppresses only the shadow observation. The calibration script now reports completed 5m candle open/completion timestamps in UTC and Beijing time plus six-decimal close/RSI for BTC, ETH, and SOL. Focused and full live test suites passed; live website alignment remains an Acceptance-only read-only check.

### 2026-07-14 - FRONTEND-UI-1 Logic-Chain Prototype Refresh
- **Status**: Completed
- **Zone**: Execution
- **Description**: Refine the local frontend prototype so entry, stop-loss, take-profit, state tags, and archive summaries communicate the agreed visual logic chain without backend integration.
- **Handoff**: None
- **Notes**: Kept the prototype self-contained with demo data. Entry flow now expresses completed 1h data, 1h price-band break, 1h RSI threshold, BandWidth permission, completed 5m data, previous-5m high/low break, account/orderbook confirmation, then a capsule-shaped protected-open confirmation. NORMAL management expands into explicit price-condition and stop-adjustment pairs; SPECIAL/EXSPECIAL show their active protection/target sequence. BTC demo state is explicitly long. Archive details state that future saved snapshots must be displayed directly rather than redrawn. The planned read-only backend connection and all temporary runtime/API/proxy changes were intentionally removed at user request; Planning must issue a new handoff before any connection work resumes.

### 2026-07-14 - FRONTEND-1 Read-Only Live Dashboard Connection
- **Status**: Completed
- **Zone**: Execution
- **Description**: Connect the revised Vinext flow UI to authoritative Python runtime observations, explicit node/connector states, read-only SQLite archive data, runner status, and immutable future archive snapshots.
- **Handoff**: `/private/tmp/bbmr_frontend_backend_connection_execution_v2.md`, `/private/tmp/bbmr_frontend_backend_connection_acceptance_v2.md`
- **Notes**: V2 supersedes the earlier FRONTEND-1 handoffs after the user rebuilt the prototype. Added runner-side atomic observation snapshots, a 127.0.0.1 stdlib GET-only dashboard API, thin Vinext GET proxies, immediate/30-second React polling, backend-owned explicit node/connector state, read-only archive listing, and immutable post-close SVG snapshots. The UI retains the eight-node entry chain and condition/action management lanes; step 8 remains the capsule confirmation node. Acceptance rework makes `entry_unprotected` explicitly blocked/tagged with all branches muted, renders branch-divider segments from backend `branch_connectors`, and freezes an archive SVG from closing-trade state rather than `current.json`. No browser/API order, config, runner-control, or SQLite write path was added. Verified live and full Python suites plus frontend test/build/lint; live page walk-through is pending a running local server and non-ordering fixture state.
- **Follow-up**: The local Dashboard API and Vinext frontend server were started for the user after a manual-position display report. The current live snapshot showed SOL was adopted at 08:36 UTC then archived as `exspecial_defensive_exit` at 08:37 UTC, so no active position remained to render. The UI now renders muted node connectors even while live data is unavailable, preventing the flow from visually collapsing.
- **Follow-up**: Added backend-owned `bandwidth` status/allow/reason data to the snapshot/API and placed `BandWidth 状态` next to completed-1h slope in the right-side panel. Older snapshots are supplemented from the latest persisted `bandwidth_state_observed` event through the read-only API.
- **Follow-up**: Expanded the right-side BandWidth view with raw value, percentile, and 1h/3h changes. The bottom panel holds only the current poll's terminal messages in `current.json` (maximum 40 lines), never in SQLite or a historical log. Current/waiting nodes and connectors now use yellow; passed states remain green.
- **Follow-up**: Replaced the dense combined slope/BandWidth tag with two independent UI cards. The BandWidth card compares current percentile and 1h change directly against their warning lines without exposing configuration-file terminology. Frontend test/build and lint passed (one pre-existing archive-image lint warning remains).

### 2026-07-14 - Frontend And Live Runtime Integration Planning Handoff
- **Status**: Planned
- **Zone**: Planning
- **Description**: Start a fresh Planning Zone to define the smallest safe connection between the untracked frontend prototype and the accepted Python live runner/SQLite state.
- **Handoff**: `/private/tmp/bbmr_frontend_integration_planning_handoff.md`
- **Notes**: Planning starts read-only and discussion-first. It must separate monitoring from safety-critical runner/config/order controls, avoid direct frontend writes to live SQLite, and leave current dirty-main/Git classification to Maintenance.

### 2026-07-14 - STRATEGY-10B Independent Acceptance
- **Status**: Completed
- **Zone**: Acceptance
- **Description**: Independent read-only review of the completed `STRATEGY-10B` managed-position lifecycle and authorized SPECIAL/EXSPECIAL YAML field split.
- **Handoff**: `/private/tmp/bbmr_strategy_revision_acceptance.md`
- **Notes**: User reported independent Acceptance passed. `STRATEGY-10A` and `STRATEGY-10B` now form the accepted strategy baseline. No strategy implementation work remains from these task books; Git/worktree baseline organization is the next Maintenance step.

### 2026-07-14 - STRATEGY-10B Managed-Position Lifecycle Handoff
- **Status**: Completed
- **Zone**: Execution
- **Description**: User confirmed `STRATEGY-10A` passed and authorized the sequential move into `STRATEGY-10B` for NORMAL/SPECIAL/EXSPECIAL managed-position lifecycle behavior.
- **Handoff**: `/private/tmp/bbmr_strategy_revision_execution.md`
- **Notes**: Replaced the authorized legacy YAML field with independent SPECIAL/EXSPECIAL fractions and strict legacy-key rejection. Added restart-safe managed-regime state, SPECIAL rolling targets, sticky EXSPECIAL half-band targets, frozen staged trailing updates, target journal events, and terminal states for both strategy and manual-adopted positions. Acceptance rework also initializes and persists SPECIAL at the entry-price fallback when no completed 1h candle and no valid history exist, while preserving existing EXSPECIAL state unchanged. Existing reduce-only close, exchange-zero verification, stop cancellation/archive ordering, entry/BandWidth/shadow behavior, manual-order boundary, sizing, and mainnet gate remain unchanged. Focused, live, and full tests passed; independent Acceptance later passed.

### 2026-07-14 - STRATEGY-10A Entry Guard And Shadow Evidence
- **Status**: Completed
- **Zone**: Execution
- **Description**: Implementing completed-1h BandWidth entry guard, previous-5m-extreme production trigger, shadow observations, and EXSPECIAL/invalid-slope entry routing.
- **Handoff**: `/private/tmp/bbmr_strategy_revision_execution.md`
- **Notes**: Added YAML-driven completed-1h BandWidth guard and one-per-bucket terminal/SQLite observations, previous-completed-5m high/low production entry trigger, restart-safe shadow trigger MFE/MAE evidence, EXSPECIAL entry blocking, and invalid-slope 2x/SPECIAL entry marking. Existing position management was intentionally excluded from this batch and was completed separately in accepted `STRATEGY-10B`.

### 2026-07-14 - Revised Strategy Execution, Acceptance, And Maintenance Handoffs
- **Status**: Completed
- **Zone**: Planning
- **Description**: Prepared two sequential strategy-critical implementation batches: entry/BandWidth/shadow telemetry first, then SPECIAL/EXSPECIAL managed-position behavior. Each batch has an independent Acceptance contract, followed by a read-first Maintenance baseline task.
- **Handoff**: `/private/tmp/bbmr_strategy_revision_execution.md`, `/private/tmp/bbmr_strategy_revision_acceptance.md`, `/private/tmp/bbmr_strategy_revision_maintenance.md`
- **Notes**: `STRATEGY-10A` and `STRATEGY-10B` both completed and passed Acceptance. BandWidth is visible once per completed-1h bucket per symbol and persisted for replay. Valid user-edited YAML remains the runtime authority for config-backed values. Maintenance baseline organization remains separate and must not commit, merge, or push without explicit user approval.

### 2026-07-14 - Consolidate Revised BBMR Strategy Consensus
- **Status**: Completed
- **Zone**: Planning
- **Description**: Consolidated the user-approved BandWidth entry guard, previous-5m-extreme production trigger, and NORMAL/SPECIAL/EXSPECIAL position-management chains into the active strategy consensus.
- **Handoff**: None
- **Notes**: This entry was documentation-only when written. The planned target was subsequently implemented by `STRATEGY-10A` and `STRATEGY-10B`, and both batches passed independent Acceptance.

### 2026-07-14 - Three-Tier Completed-1h Slope State
- **Status**: Completed
- **Zone**: Execution
- **Description**: Replaced the binary slope predicate with shared NORMAL, SPECIAL, and EXSPECIAL state for 1h RSI setup selection, new strategy-entry leverage, and EXSPECIAL-only midband TP.
- **Handoff**: None
- **Notes**: Config now uses 40/60 normal RSI, 32/68 strict RSI, and 0.09%/0.25% slope thresholds. Only EXSPECIAL writes the existing adverse-slope TP state; SPECIAL uses strict RSI and 2x entry leverage without TP. No DB schema, 15m/5m, normal trailing-stop, sizing, or manual-position leverage changes.

### 2026-07-13 - Special TP Market-Price Timeout Guard
- **Status**: Completed
- **Zone**: Execution
- **Description**: Keeping managed positions under trailing-stop management when a special TP price read times out.
- **Handoff**: None
- **Notes**: The special TP `get_market_price()` boundary now records a symbol-level WARN and skips only that TP check on recoverable network failure; normal trailing-stop maintenance and later symbols continue. No TP price source, order submission, strategy, sizing, leverage, stop, or persistence path changed.

### 2026-07-13 - Adverse-Slope 1h RSI Thresholds
- **Status**: Completed
- **Zone**: Execution
- **Description**: Selecting stricter or normal 1h setup RSI thresholds from each symbol and direction's completed-candle adverse-slope state.
- **Handoff**: None
- **Notes**: Added configurable normal `35/65` and adverse-slope `32/68` RSI thresholds; set the shared slope threshold to `0.002`; reused the signed-slope calculation for setup creation and TP state. Incomplete or invalid slope history uses the stricter threshold. No Bollinger, 15m/5m, sizing, stop, TP, or persistence paths changed; the existing leverage path still uses the same shared special-state predicate.

### 2026-07-13 - Entry Open-Order Timeout Guard
- **Status**: Completed
- **Zone**: Execution
- **Description**: Keeping the live runner alive when entry-side open-order checks time out after the initial poll reads succeed.
- **Handoff**: None
- **Notes**: Added a minimal recoverable-network wrapper around `maybe_open_strategy_trade()` so `fetch_open_orders()` timeouts from the entry-side exchange guard now append `recoverable_network_error`, print `[WARN] <symbol> entry check network error; waiting for next cycle`, and skip entry work until the next cycle instead of crashing the loop. Scope stayed limited to recoverable entry-check network errors; no strategy, sizing, stop, TP, or order-placement behavior changed. Verified with `.venv/bin/python -m pytest tests/live/test_live_run.py -q` and `git diff --check`.

### 2026-07-09 - Market Spread Guard L2 Top Of Book
- **Status**: Completed
- **Zone**: Execution
- **Description**: Switching the pre-entry market spread guard from ticker bid/ask to Hyperliquid L2 top-of-book bid/ask.
- **Handoff**: None
- **Notes**: `HyperliquidClient.fetch_market_quote()` now reads `fetch_order_book(..., limit=1)` best bid/ask and returns top-book mid as the pre-entry reference. `_entry_market_quality()` now computes spread as `(best_ask - best_bid) / top_book_mid * 10000`, so ticker `impactPxs` bid/ask no longer drives the guard. Confirmed local ccxt Hyperliquid declares `fetchOrderBook=True`. No entry signal, sizing, leverage, order type, depth/VWAP guard, or mainnet backlog changes. Verified with `.venv/bin/python -m pytest tests/live/test_hyperliquid_client.py tests/live/test_trailing_runtime.py tests/live/test_live_config.py -q`.

### 2026-07-09 - Startup Market Load Timeout Guard
- **Status**: Completed
- **Zone**: Execution
- **Description**: Keeping the live runner alive when Hyperliquid client startup times out before the first poll.
- **Handoff**: None
- **Notes**: Added a minimal startup wrapper around `HyperliquidClient(config)` so recoverable `load_markets()` network failures now append `recoverable_network_error`, print `[WARN] live startup network error; waiting for next cycle`, and retry on the next cycle instead of crashing before `_poll_once()`. Scope stayed limited to startup recoverable-network handling; no strategy, sizing, stop, TP, or exchange-order behavior changed. Verified with `.venv/bin/python -m pytest tests/live/test_live_run.py -q` and `git diff --check`.

### 2026-07-08 - Manual Adopted Adverse Slope TP
- **Status**: Completed
- **Zone**: Execution
- **Description**: Extending adverse-slope special TP state from strategy-only trades to all system-managed positions, including manual_adopted.
- **Handoff**: None
- **Notes**: Removed the `trade.source != "strategy"` exclusion from `update_adverse_slope_take_profit()`, updated consensus docs to include `manual_adopted` while keeping adverse-slope entry leverage strategy-only, and adjusted tests for manual-adopted special state, `[SPECIAL]` output, and SAFETY-3 zero-position close verification. No entry signal, RSI, sizing, leverage selection, trailing-stop chain, or mainnet backlog changes. Verified with `.venv/bin/python -m pytest tests/live/test_trailing_runtime.py tests/live/test_live_run.py tests/test_config.py -q`.

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
