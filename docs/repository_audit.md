# BBMR 当前仓库全量工程审计

审计日期：2026-07-20
审计范围：当前磁盘工作区快照（包含用户已有的未提交和未跟踪内容）
审计方式：只读源码/配置/依赖/历史元数据检查，Python 全量测试与覆盖率，未启动 runner，未向交易所写入，未执行 Git 写操作。

> 重要基线：本次结论针对当前脏工作区，不等同于某个 Git commit。最新已验收策略切片仍是 STRATEGY-13；STRATEGY-14 在审计开始时处于“执行完成、独立验收待定”。当前 `trend_riding.mode = shadow`，mainnet 下单仍被代码锁死。本报告不是 STRATEGY-14 的验收结论。

## 1. 执行摘要

| 级别 | 数量 | 结论 |
|---|---:|---|
| P0 | 0 | 当前 shadow/testnet/mainnet-lock 基线下，未确认可立即造成主网资金损失的已激活故障。 |
| P1 | 11 | 实盘前必须解决；涉及权益/敞口计算、止损真实性、订单幂等、并发身份、隐式 builder fee/referrer 和真实滑点边界。 |
| P2 | 11 | 应在扩大运行范围前处理；涉及恢复语义、持久化不变量、运维脚本、密钥权限、依赖复现和前端版本边界。 |
| P3 | 7 | 工程收缩与可维护性问题；主要是旧 research 孤岛、starter 残留、无效配置和兼容 shim。 |

最重要的结论：379 个 Python 测试全部通过、总覆盖率 86%，但测试使用的 FakeExchange 在三个关键点与当前 pin 的 CCXT 4.5.58 Hyperliquid 真实语义不同：`USDC.total`、`markPrice/notional`、首次下单初始化副作用。因此“测试全绿”目前不能证明真实账户风险口径和交易副作用正确。

在修复 P1 前，不建议把 trend mode 从 `shadow` 切到 `live`，也不建议解除 mainnet 锁。

## 2. 运行入口、核心模块与完整业务调用链

### 2.1 Python live runner

入口：`src/bbmr/live/run.py:23 main`，模块入口位于 `run.py:285-286`。

```text
python -m bbmr.live.run --live-config <yaml>
  -> load_project_env                         live/env.py:5
  -> load_live_config                        live/config.py:88
     -> load_config(active strategy YAML)    config.py:308
  -> LiveStateStore                          live/state_store.py:130
  -> runner lock                             live/run.py:248
  -> HyperliquidClient                       live/hyperliquid_client.py:32
  -> LiveRuntime.__post_init__               live/trailing_runtime.py:38
     -> expire/rebuild pending setup
     -> restore trend pending/shadow state
  -> scheduler                               live/run.py:53-70,198-245
  -> _poll_once                              live/run.py:84
     -> fetch balance + positions            :91-92
     -> fetch 1h/15m/5m completed features   trailing_runtime.py:1654-1662
     -> BandWidth observation                run.py:104-106
     -> trend shadow/pending advance          :107-112
     -> exchange/local reconciliation        :113 -> trailing_runtime.py:746
     -> managed trend position               :119-121 -> update_trend_trade
     -> managed MR/manual position           :123-147
        -> adverse-slope state/TP
        -> staged trailing stop replacement
     -> trend fixed-limit entry              :150-153 -> maybe_open_trend_trade
     -> mean-reversion market entry          :155 -> maybe_open_strategy_trade
     -> SQLite/event persistence             state_store.py:263-724
     -> atomic dashboard snapshot            dashboard.py:32-43
```

交易所读写集中在 `src/bbmr/live/hyperliquid_client.py`：余额/仓位/行情在 `:55-105`，杠杆、入场、平仓、保护止损、撤单在 `:136-191`。策略计算集中在 `src/bbmr/trailing.py` 和 `src/bbmr/trailing_features.py`。

### 2.2 Dashboard

Python API 入口：`src/bbmr/live/dashboard.py:218 main`。

```text
runner -> atomic current.json + SQLite
       -> ThreadingHTTPServer(127.0.0.1:8765)
          -> /api/dashboard/overview
          -> /api/dashboard/archives
          -> /api/dashboard/archives/{id}[/snapshot]
       -> frontend Next/Vinext GET proxies
       -> React overview/archive pages
```

Python 服务只绑定 `127.0.0.1`（`dashboard.py:218-220`）。四个前端只读代理位于 `frontend/app/api/dashboard/**/route.ts`；首页入口为 `frontend/app/page.tsx:64`，Worker 入口为 `frontend/worker/index.ts:28`。

### 2.3 运维/验收入口

- `scripts/hyperliquid_acceptance.py:12 main`：真实 testnet 小额下单/止损/平仓验收。
- `scripts/hyperliquid_rsi_calibration.py:14 main`：只读 RSI 校准。
- `scripts/live_safety_journal.py:10 main`：SQLite 只读安全事件查询。
- 前端命令见 `frontend/package.json:8-14`：Vinext dev/build/start、build 后 Node test、ESLint。

### 2.4 已移除的旧 research 子图

AUDIT-G7-E 已移除无现行 production entry 的 Phase-1A research island 与 permissive loader fallback。当前 package 只保留 active trailing strategy、live runtime 和其 shared indicators/backtest support。

## 3. P0

未确认 P0。

这不表示代码已经适合主网。这里的 P0 判定考虑了当前 `trend_riding.mode=shadow`、testnet 配置以及 `LiveRuntime.can_place_orders()` 对 mainnet 恒为 false（`trailing_runtime.py:564-567`）。下列 P1 均应视为“解除主网锁或切 trend live 前的硬门槛”。

## 4. P1：实盘前必须修复

### P1-01 账户权益重复计入未实现盈亏

- 文件/函数：`src/bbmr/live/hyperliquid_client.py:55-62 HyperliquidClient.fetch_balance`；消费端 `trailing_runtime.py:178-187,908-922,1301-1303`。
- 触发条件：账户已有正或负未实现盈亏，此时评估新入场。
- 问题：当前 pin 的 CCXT Hyperliquid 已把 `marginSummary.accountValue` 映射为 `USDC.total`，代码又加了一遍各仓 `unrealizedPnl`。Hyperliquid 官方也说明 account value 包含 unrealized PnL（[Portfolio graphs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-graphs)、[Margining](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/margining)）。
- 影响：正浮盈放大下单名义金额和账户总上限；负浮盈被重复扣减。属于直接资金规模错误。
- 测试缺口：`tests/live/test_hyperliquid_client.py:77-80` 反而断言 `10000 + 10 = 10010`，把错误语义固定进测试。
- 建议：equity 直接使用 CCXT `USDC.total/accountValue`；独立核对 available 应映射 `free` 还是 Hyperliquid `withdrawable`；用真实 CCXT response shape 增加回归测试。

### P1-02 已有仓位名义敞口使用 entryPrice 冒充 markPrice

- 文件/函数：`hyperliquid_client.py:64-79 fetch_positions`；`trailing_runtime.py:1706-1711 _exchange_positions_notional`；cap 检查在 `:186,919-922`。
- 触发条件：已有仓位价格相对开仓价明显上升，再尝试开另一币种/趋势仓。
- 问题：当前 ccxt 4.5.58 Hyperliquid `parse_position` 返回 `markPrice=None`，但提供 `notional=positionValue`；应用层于是回退到 `entryPrice`。
- 影响：上涨后的真实敞口被低估，新的入场可能令总名义敞口突破 `max_total_notional_fraction`。
- 测试缺口：FakeExchange 手工提供 `markPrice=105`；cap 测试也手工构造有效 mark，未覆盖真实 adapter 形状。
- 建议：在 `ExchangePosition` 保留 CCXT `notional` 并优先用于账户 cap；否则取得有效实时 mark；两者都缺失时 fail closed。

### P1-03 每轮只取一次 balance/positions，跨币种预算使用陈旧快照

- 文件/函数：`src/bbmr/live/run.py:91-93,100-168 _poll_once`；`trailing_runtime.py:178-187,908-922`。
- 触发条件：同一 poll 中前一个 symbol 成交或创建 pending order，后一个 symbol 紧接着评估入场。
- 问题：BTC/ETH/SOL 顺序共享 poll 开始时的一份 balance/positions；前一币种的成交或订单占用没有反馈到后一币种的 available/cap 检查，pending order notional 也未全局预留。
- 影响：多个币种在同一轮分别通过风控，但合计超出账户预算。
- 测试缺口：`tests/live/test_live_run.py:496-504` 只验证多币种单次 fetch，没有“首币成交后次币评估”的变更场景。
- 建议：任何订单状态突变后刷新账户状态，或引入单一账户级 reservation ledger，把 open/ambiguous/pending order 的名义金额纳入预算。

### P1-04 只信任本地 stop order id，不验证交易所止损仍然存活

- 文件/函数：`trailing_runtime.py:746-814 reconcile_symbol`，尤其 `:781-802`。
- 触发条件：保护止损在交易所被手动取消、拒绝、过期或外部修改，但 SQLite 仍保存 `system_stop_order_id`。
- 问题：reconcile 只有在 `entry_unprotected` 或 ID 为空时补止损；ID 非空即视为已保护，从不查询该订单的真实状态。
- 影响：真实持仓可长期无保护，而本地状态/dashboard 仍显示 open/protected；SPECIAL/EXSPECIAL 时尤其可能停止正常 trailing 更新。
- 测试缺口：没有“本地 ID 存在、交易所订单消失”的回归测试。
- 建议：每轮或至少每个已完成 candle 校验系统止损的 exchange truth（存在、open、reduce-only、方向、数量、触发价）；不一致时进入持久化 `entry_unprotected/protect_recovery` 状态并阻断新仓。

### P1-05 止损替换的 create-new/cancel-old 窗口不具备恢复语义

- 文件/函数：`trailing_runtime.py:1360-1387 _cancel_system_stop/_replace_stop`；调用方 `:1019-1037 update_stop`。
- 触发条件：新保护止损创建成功，但取消旧止损出现网络超时/未知结果。
- 问题：旧单 cancel 在创建 try/except 之外；raw 网络异常不会转成 `StopReplacementError`，managed-position 主循环也没有外围恢复处理。新 ID 尚未持久化，SQLite 仍指向旧 ID。
- 影响：runner 可直接退出；交易所可能同时存在旧/新止损，而本地不拥有新单，重启后无法确定真相。
- 测试缺口：只覆盖新 stop 创建失败或缺 ID，没有覆盖“新建成功后 cancel 超时/response lost”。
- 建议：持久化 replacement intent（old/new ID、cancel_pending）；先记录新单，再可恢复地撤旧单；重启按 exchange truth 收敛；网络错误不得让管理循环无状态退出。

### P1-06 均值回归 market entry 缺少持久化 intent 与幂等 client ID

- 文件/函数：`trailing_runtime.py:934-953 maybe_open_strategy_trade`；下单适配 `hyperliquid_client.py:139-148`。
- 触发条件：交易所已接受下单，但响应丢失，且紧接着查询仓位也超时或暂时看不到 eventual-consistency 结果。
- 问题：代码只写 `entry_order_not_confirmed` event 并保留 setup，没有 durable intent/client order id；下一轮可再次提交同一个 market entry。
- 影响：重复开仓、仓位超额，之后止损数量和本地状态更加难以恢复。
- 测试缺口：未覆盖“提交已成功 + 响应丢失 + 仓位暂不可见 + 下一轮重试”。
- 建议：像 trend pending 一样，在发送前持久化确定性 client ID 和 entry intent；unknown outcome 只能 reconcile，不能重新提交，直至明确 terminal。

### P1-07 `maintain_exchange_stop=false` 或无下单权限时仍可能把交易标成 open

- 文件/函数：`live/config.py:38-60 LiveExecutionSection`；`trailing_runtime.py:770-801 reconcile_symbol`、`:957-1016 maybe_open_strategy_trade`、`:1368-1387 _replace_stop`。
- 触发条件：关闭 `maintain_exchange_stop`，或 manual adoption/recovery 时 `allow_orders=false`/dry-run。
- 问题：`_replace_stop` 可无动作返回；上层随后把 trade 标成 open 或输出“adopted into trailing stop management”，没有已确认 stop ID 的硬不变量。
- 影响：本地状态声称已保护，交易所实际没有保护止损。
- 测试缺口：缺少 false/no-permission/manual-adopt stop-create-failure 组合测试。
- 建议：执行模式强制 `maintain_exchange_stop=true`；只有确认有效 stop ID 后才允许 `status=open`。观察模式必须使用不同状态，不能伪装为保护完成。

### P1-08 runner 锁与持久化身份没有绑定真实钱包

- 文件/函数：`run.py:38-49,248-267`；`trailing_runtime.py:31-36,561-562`。
- 触发条件：同一钱包使用不同 SQLite 目录启动两个 runner；或更换钱包后复用旧 SQLite。
- 问题：锁只按 SQLite 父目录，`account` 永远是字符串 `default`，position key 不含钱包指纹。Store 还在取得 runner lock 前打开/迁移。
- 影响：同一账户可被两个进程并发交易；旧钱包的本地 trade/stop ID 可能被应用到新钱包，旧账户仓位则失去管理。
- 测试缺口：仅覆盖相同路径锁冲突，没有跨路径同钱包和 DB-wallet mismatch。
- 建议：按 env + 规范化 wallet address 建锁；SQLite 保存不可逆 wallet fingerprint/env metadata 并在 mismatch 时拒绝启动；先锁再打开/迁移 store。

### P1-09 symbols 列表不拒绝重复值

- 文件/函数：`live/config.py:63-65 LiveSymbolsSection`；循环 `run.py:38,93,100`。
- 触发条件：live YAML 出现重复或等价 symbol（例如 `BTC`/`BTC/USDC:USDC`）。
- 问题：没有 non-empty、normalize、unique validator。同轮第二次处理共享陈旧 positions，可能把第一次新开的本地仓判断为“交易所仓位消失”，取消 stop/归档后再次开仓。
- 影响：重复下单、保护止损被取消、本地账本漂移。
- 测试缺口：无重复/等价 symbol 配置测试。
- 建议：配置加载时规范化并拒绝重复、空值和不支持 symbol；运行循环只使用校验后的 canonical list。

### P1-10 CCXT 首次下单会隐式授权第三方 builder fee 并设置 referrer

- 文件/函数：应用构造器 `hyperliquid_client.py:39-49 _create_exchange`；当前 pin 依赖 `.venv/.../ccxt/hyperliquid.py:234-239,1700-1777,1757-1759,2035-2048,2224-2232`。
- 触发条件：真实 ccxt client 第一次执行 create order。
- 问题：应用只设置 `defaultType`，而 ccxt 4.5.58 默认 `builderFee=True`，初始化会签名发送 `approveBuilderFee`（默认 max fee 0.01%）和 `setReferrer`（默认 `CCXT1`）；后续 order action 自动带 builder 字段。这些外部写入和持续费用没有出现在项目配置/共识中。
- 影响：用户未明确批准的第三方授权、referral 归因和额外交易成本；依赖升级还可能静默改变默认值。
- 测试缺口：测试全部注入 FakeExchange，未实例化真实 ccxt，也不检查首次下单前后的私有 action。
- 建议：显式关闭 `builderFee`；对 referrer 行为采用受支持且可测试的显式策略（拒绝、固定或用户批准），不能依赖第三方默认值；增加 spy/contract test 证明没有未授权 action/builder 字段。

### P1-11 项目 1% slippage 配置只是事后告警，CCXT 默认下单包络约 5%

- 文件/函数：`hyperliquid_client.py:85-97,139-170`；`trailing_runtime.py:924-943,1323-1336`；ccxt 默认位于 `.venv/.../ccxt/hyperliquid.py:234-239,2078-2103`。
- 触发条件：spread precheck 后价格跳变、薄订单簿或较大订单冲击。
- 问题：`max_entry_slippage_bps=100` 只在成交后写 WARN；下单未向 CCXT 传 slippage，CCXT 默认用约 5% envelope 构造 IOC limit，且应用传的是 ticker last，不是刚检查的 side-aware top of book。
- 影响：成交可显著偏离 5m 信号价，真实止损风险和回测假设失真；事后告警无法撤销损失。
- 测试缺口：现有测试明确允许约 476 bps 成交后继续管理，没有验证最终提交价格包络。
- 建议：这是策略/执行语义变更，需规划批准。若 1% 应是硬上限，则把 CCXT slippage 参数与批准的 L2 reference 绑定，超限宁可 IOC 不成交；若接受 5%，应在共识和风险预算中明确。

## 5. P2：扩大运行范围前处理

### P2-01 启动时瞬时行情失败会永久删除 pending setup

- 文件/函数：`trailing_runtime.py:38-48,1457-1507`。
- 触发条件：重启时拉取 1h/15m/5m candle 出现临时网络错误。
- 影响：仍有效的入场 setup 被删除并记为 discarded，重启前后策略语义不一致。
- 建议：可恢复 transport error 应保留并重试；只有通过当前 candle 明确证明语义失效时才删除。

### P2-02 `--dry-run` 仍写真实 SQLite 生命周期

- 文件/函数：`trailing_runtime.py:997-1016`，以及 reconcile/shadow persistence 路径。
- 触发条件：用 production SQLite 运行 `--dry-run`。
- 影响：可创建 phantom open trade、删除 setup、写 entry event，后续真实 runner 会把模拟状态当真。
- 建议：dry-run 使用独立 DB/事务回滚/明确 simulation namespace；至少拒绝与 production storage path 共用。

### P2-03 active trade 唯一性与 state/event 原子性不足

- 文件/函数：`state_store.py:138-151,263-345,347-390` 及多处 `append_event`。
- 触发条件：锁绕过、故障重试或进程在状态 commit 与 event commit 之间崩溃。
- 影响：同一 `exchange_position_key` 可存在多个 active row，`fetchone()` 无排序地选择一个；状态已更新但审计 event 丢失，或反之。
- 建议：增加 active position 的 partial unique invariant；将本地状态变更与对应 event 放入同一 SQLite transaction。外部订单仍用 durable intent/outbox 协调。

### P2-04 顶层未知异常不写 error lifecycle，runner 可能静默退出

- 文件/函数：`run.py:48-70,84-169`；dashboard lifecycle 只写 starting/running。
- 触发条件：止损 cancel raw error、数据不变量异常或未分类适配器异常。
- 影响：runner 退出后只剩交易所静态 stop；动态 trailing/TP 停止，dashboard 也未必显示 error。
- 建议：顶层 finally/except 写 durable error lifecycle 和 CRITICAL event；配套外部 supervisor。只对明确可恢复的 per-symbol 错误隔离，不能吞掉不变量错误。

### P2-05 testnet acceptance 脚本失败清理可留下裸仓

- 文件/函数：`scripts/hyperliquid_acceptance.py:43-51 main`。
- 触发条件：entry 成功但 stop 创建失败；或 close 失败后进入 finally。
- 影响：前者留下未保护 testnet 仓位；后者仍会取消 stop，留下裸仓。没有最终 fetch_positions 证明归零。
- 建议：任何可能成交后都进入 durable cleanup；只有确认仓位为零才取消 stop，否则保留 stop 并输出人工清理证据。

### P2-06 realized PnL 归因会混入无关成交

- 文件/函数：`hyperliquid_client.py:105-134 fetch_recent_realized_pnl`。
- 触发条件：入场后同 symbol 存在多次手动/系统 opposite-side 成交或部分平仓。
- 影响：最多 50 笔反向成交都可能被聚合到当前 trade，归档 PnL/费用失真，影响策略评估而非直接下单。
- 建议：记录 close order/client ID 并按实际 close qty/fills 归因；未知时标记 unknown，不拼凑精确值。

### P2-07 仓位 adapter 对 schema 漂移没有 fail closed

- 文件/函数：`hyperliquid_client.py:64-79 fetch_positions`。
- 触发条件：CCXT 返回 `contracts=0` 但 `contractSize` 非空，或 side 缺失/未知。
- 影响：`contracts or contractSize` 会虚构非零数量，任意未知 side 会被映射为 short。当前 pin 暂不直接触发，但升级后可能错误接管/反向管理仓位。
- 建议：严格按 CCXT unified Position：contracts 只表示数量，side 必须 allowlist；无效 payload 应告警并阻断相关交易。

### P2-08 私钥环境文件权限为 0644

- 文件/函数：仓库根 `.env`（已忽略，值未在报告中读取或披露）。
- 触发条件：同机其他本地账户可以访问该路径。
- 影响：wallet private key 可被读取。Git tracked/history 定向扫描未发现该文件或已知格式私钥进入版本库。
- 建议：将文件权限收紧为 0600，并优先迁移到 OS keychain/受控 secrets store；启动时可检查权限并 fail closed。

### P2-09 Python 交易环境没有可复现 lock

- 文件/函数：`pyproject.toml:10-16`。
- 触发条件：新机器/重建 venv/宽范围依赖发布新版本。
- 影响：pandas、Pydantic、PyYAML 等行为及传递依赖漂移，测试环境与 live 环境不可复现。只有 ccxt 精确 pin。
- 建议：跟踪带传递依赖和 hashes 的 lock/constraints；升级必须走显式 diff 和资金安全回归。

### P2-10 `frontend/` 是无 commit 的嵌套 Git 仓库

- 文件/函数：`frontend/.git`；父仓 `git status` 只显示 `?? frontend/`，子仓所有文件均未跟踪且 `main` 无 commit。
- 触发条件：尝试把 dashboard 纳入父仓、CI 或部署。
- 影响：父仓不能正常 review/version/rollback 前端及 lockfile；普通 add 会碰到 embedded-repo/gitlink 语义。
- 建议：由维护区在明确授权后处理单个 `frontend/.git` 元数据边界，再由父仓跟踪实际源文件。本次不删除或修改。

### P2-11 Dashboard 复制策略判定且前端硬编码 symbols

- 文件/函数：`dashboard.py:45-90 observe`；`frontend/app/page.tsx:7,64-95`。
- 触发条件：策略入场顺序/条件再次调整，或 live config 修改 symbol 集合。
- 影响：dashboard 自己重新调用 `evaluate_setup`、私有 5m signal 和 BandWidth guard，可能与 runner 真正走过的分支漂移；前端忽略 snapshot 已返回的 `configured_symbols`，显示集合也会漂移。它不直接下单，但可能误导人工操作和验收。
- 建议：runner 生成权威 decision trace，dashboard 只格式化；前端从 `configured_symbols` 渲染。

## 6. P3：收缩与可维护性

### P3-01 已收口：旧 Phase-1A research scaffold

- 状态：AUDIT-G7-E 已移除无外部消费者的 production、test 与 YAML 孤岛，并删除旧 loader fallback；当前 active package 只保留 trailing 策略。

### P3-02 已收口：未接入 frontend starter 残留

- 状态：AUDIT-G7-E 已在 M0 外部备份后移除 starter 残留及其 direct manifest entries；本地只读 dashboard、routes、worker 与测试保留。

### P3-03 已收口：active YAML/schema 的无效控制项

- 状态：AUDIT-G7-E 已删除 inert fields，并由 strict active schema 拒绝旧或未知 strategy identity 和额外字段。

### P3-04 已收口：runner required runtime interface

- 状态：AUDIT-G7-E 改为 production direct calls；测试 fake 缺失接口会立即失败。

### P3-05 已收口：重复 legacy symbol adapter

- 状态：AUDIT-G7-E 随 unsupported island 移除旧 adapter；active live adapter 保留。

### P3-06 已收口：小型死成员

- 状态：AUDIT-G7-E 移除 `LiveRuntime.pending` 与 `HyperliquidClient.missing_credentials`，保留 G5 active 的 `StateStore.active_trend_pendings()`。

### P3-07 已收口：可取消的 direct dependencies

- 状态：AUDIT-G7-E 移除 NumPy 与五项 frontend direct manifest entries；锁文件重建留给 AUDIT-G7-M1。

## 7. 异常、并发、状态、持久化与安全结论

### 已确认风险

- 异常分类只覆盖部分 fetch/entry-check 网络错误；managed stop cancel、manual adoption 和部分 close cleanup 仍能让 runner 无持久化退出。
- 并发锁只保护一个 SQLite 目录，不保护钱包身份；SQLite active row 也无唯一约束。
- 外部订单与本地状态之间缺少统一 durable intent。Trend limit 有 pending 状态，MR market entry 和 stop replacement 没有同等级恢复能力。
- SQLite 大多数单操作会 commit，dashboard JSON/SVG 使用临时文件 + `os.replace`，单文件落盘较安全；但 trade 状态与 event 不是同一事务。
- `.env` 未跟踪且定向历史扫描未命中已知私钥格式，但本地权限过宽。
- 当前 CCXT 依赖存在未显式批准的首次下单私有 action/费用副作用。

### 已检查且未发现

- 未发现 tracked `.env`、已知私钥前缀或 0x64-hex 私钥进入 Git 当前文件/定向历史扫描。
- Dashboard 绑定 loopback；archive ID 受 regex 约束；SQLite 查询使用参数；SVG 文本使用 HTML escape。未发现明确的命令、路径或 SQL 注入。
- 未发现 GitHub Actions、Docker、Terraform/Kubernetes 等额外部署攻击面。
- 前端 API 没有应用层鉴权，但当前 Python upstream 仅绑定 localhost；只有未来通过代理公开时才升级为真实访问控制风险。

## 8. 测试与覆盖率审计

执行命令（coverage 文件写到 `/private/tmp`，避免污染仓库）：

```bash
PYTHONDONTWRITEBYTECODE=1 COVERAGE_FILE=/private/tmp/bbmr_repository_audit.coverage \
  ./.venv/bin/python -m pytest -p no:cacheprovider \
  --cov=bbmr --cov-report=term-missing:skip-covered tests -q
```

结果：379 tests passed；3,349 statements，461 missed，总覆盖率 86%。关键模块：

| 模块 | 覆盖率 | 关键缺口 |
|---|---:|---|
| `live/trailing_runtime.py` | 80% | trend pending recovery `590-625`、保护失败 `683-690`、side reversal `766-768`、补 stop 失败 `790-793`、ambiguous MR entry `947-949`、cancel error `1366`、stop disabled `1370`、启动 candle error `1460-1461`。 |
| `live/hyperliquid_client.py` | 86% | 测试未实例化真实 ccxt；真实 balance/position/builder/slippage 语义缺 contract test。 |
| `live/run.py` | 89% | 多币种顺序成交后的预算刷新、managed branch 网络异常、fatal lifecycle 缺口。 |
| `live/state_store.py` | 96% | 高行覆盖不能证明跨操作事务和唯一不变量。 |
| `live/dashboard.py` | 72% | HTTP handler `196-214`、归档和失败响应路径覆盖不足。 |

### 资金损失优先测试清单

1. 使用当前 pin 的真实 CCXT Hyperliquid response shape 验证 accountValue、withdrawable、positionValue/notional、markPrice=None。
2. 首次 create order 的私有调用 spy：不得发生未批准的 `approveBuilderFee`、`setReferrer`，order action 不得带未批准 builder。
3. 验证最终 Hyperliquid IOC price envelope 与批准的 slippage 上限一致，而非只测成交后 warning。
4. Stop exchange-liveness：本地 ID 存在但订单 canceled/rejected/missing/wrong qty/wrong trigger。
5. Stop replacement fault matrix：create 成功 + cancel timeout/response lost/already missing；每一步重启恢复。
6. MR market entry unknown-outcome：提交成功但响应丢失、position eventual consistency、重启、不得二次提交。
7. 同轮 BTC 成交后 ETH/SOL 风控，含 open/ambiguous pending notional reservation。
8. 同钱包不同 SQLite runner、DB-wallet mismatch、重复/equivalent symbols。
9. `maintain_exchange_stop=false`、allow_orders=false、manual adoption、dry-run 均不得产生伪 protected state。
10. acceptance cleanup 在 entry/stop/close 每个故障点都必须保留保护或确认归零。

前端测试没有运行：`npm test` 会先执行 build 并写 `dist/.next`，不符合本轮只读约束。现有 `frontend/tests/rendered-html.test.mjs` 主要是构建产物/源码 regex，缺少真实 proxy、invalid ID、upstream failure 和未来远程访问控制集成测试。

依赖 CVE 在线查询未完成：本地没有 `pip-audit`/`osv-scanner`；`npm audit` 会把依赖元数据发送给外部 registry，工具审批未获授权。本报告不声称当前依赖“无 CVE”。

## 9. 建议修复顺序

1. 先冻结运行升级：保持 trend `shadow` 和 mainnet lock。
2. 修正账户权益与名义敞口真实语义，并补真实 CCXT contract tests。
3. 显式消除/批准 CCXT builder/referrer/slippage 副作用。
4. 建立 stop exchange-liveness 与 durable replacement recovery。
5. 为 MR entry 建 durable intent/idempotency；建立账户级 reservation。
6. 绑定 runner/wallet/DB 身份，拒绝重复 symbols，补 active trade 唯一约束。
7. 补齐故障注入测试后，再讨论 trend live 或 mainnet。
8. 最后单独做 Ponytail 清理，不与资金安全改动混合。

## 10. Ponytail 收缩估算

在确认旧 research API、仓外 Sites preview 均不再受支持后，保守可减少约 2,600-2,800 行、6 个直接依赖。优先级：旧 research 孤岛 → D1/Drizzle/starter 残留 → auth/preview → 无效配置 → runtime compatibility shim → 小型死成员。

不建议为了 DRY 合并四个显式只读 API route，也不建议删除 SQLite `_ensure_*` migration、shadow evidence、trend pending 独立表或安全 gate；这些代码有当前明确职责。

## 11. 审计边界与免责声明

- 本轮只修改本报告，没有修改业务代码、测试、YAML、frontend、项目记忆、runner 或交易所状态。
- 静态审计和测试不能证明系统无漏洞，也不能替代 testnet 故障注入、真实 CCXT contract test、依赖 advisory scan 和外部部署渗透测试。
- 本报告包含资金安全建议，但不是财务建议；任何真实资金启用都应经过独立验收、最小额度 testnet/沙盒验证和明确人工放行。
