"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { actionStepIds, Archive, connectorState, EntryRisk, entrySteps, FlowKind, formatBeijing, formatPct, formatPnl, itemState, laneIds, laneLabels, Overview, Regime, stepState, StepState, trendActionStepIds, trendEntrySteps, trendManagementSteps } from "./flow-data";

const runnerCopy = { starting: "启动中", running: "运行中", stopped: "已关闭", error: "异常", unknown: "状态未知" };
const tagCopy: Record<string, string> = { manual_adopted: "手动接管", manual_size_changed: "手动加仓", entry_unprotected: "未建立保护止损" };

function Step({ title, state, connector, confirm = false }: { title: string; state: StepState; connector?: StepState; confirm?: boolean }) {
  return <><div className={`step ${state} ${confirm ? "confirm" : ""}`}><span className="node-dot" /><strong>{title}</strong></div>{connector !== undefined && <div className={`connector ${connector}`} />}</>;
}

function BranchDivider({ connectors }: { connectors: Overview["branch_connectors"] | undefined }) {
  return <div className="branch-connector" aria-label="仓位管理分支连接">{(["normal", "special", "exspecial"] as Regime[]).map((lane) => <span key={lane} className={connectorState(connectors ?? [], "opened_protected", lane)} />)}</div>;
}

const isState = (value: unknown): value is StepState => value === "passed" || value === "current" || value === "muted";
const isStepList = (value: unknown, ids: readonly string[]) => Array.isArray(value) && value.length === ids.length && value.every((item, index) => !!item && typeof item === "object" && (item as { id?: unknown }).id === ids[index] && isState((item as { state?: unknown }).state));
const isConnectorList = (value: unknown, ids: readonly string[]) => Array.isArray(value) && value.length === ids.length - 1 && value.every((item, index) => !!item && typeof item === "object" && (item as { from?: unknown }).from === ids[index] && (item as { to?: unknown }).to === ids[index + 1] && isState((item as { state?: unknown }).state));
const isStepSet = (value: unknown, ids: readonly string[]) => Array.isArray(value) && value.length === ids.length && value.every((item) => !!item && typeof item === "object" && ids.includes((item as { id?: string }).id ?? "") && isState((item as { state?: unknown }).state)) && new Set(value.map((item) => (item as { id: string }).id)).size === ids.length;
const isConnectorSet = (value: unknown, ids: readonly string[]) => Array.isArray(value) && value.length === ids.length - 1 && value.every((item) => !!item && typeof item === "object" && ids.includes((item as { from?: string }).from ?? "") && ids.includes((item as { to?: string }).to ?? "") && (item as { from: string; to: string }).from !== (item as { from: string; to: string }).to && isState((item as { state?: unknown }).state)) && new Set(value.map((item) => `${(item as { from: string }).from}:${(item as { to: string }).to}`)).size === ids.length - 1;
const ratio = (value: number | null) => value === null ? "—" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
const rank = (value: number | null | undefined) => typeof value === "number" ? `${value.toFixed(1)} / 100` : "暂无/不可用";
const price = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value) ? value.toFixed(8) : "未知";
const riskCopy: Record<string, string> = { normal: "NORMAL", special: "SPECIAL", exspecial: "EXSPECIAL", bw_shock_block: "BandWidth 冲击阻止", bw_continuation_special: "BandWidth 延续收紧", none: "暂无联动", up: "向上", down: "向下" };

function EntryRiskCard({ side, risk }: { side: "long" | "short"; risk?: EntryRisk }) {
  const linkage = risk?.linkage_state ? (riskCopy[risk.linkage_state] ?? risk.linkage_state) : "暂无/不可用";
  const effective = risk?.effective_state ? (riskCopy[risk.effective_state] ?? risk.effective_state) : "暂无/不可用";
  const rsi = typeof risk?.rsi_threshold === "number" ? risk.rsi_threshold.toFixed(0) : "暂无/不可用";
  const leverage = typeof risk?.leverage === "number" ? `${risk.leverage}x` : "暂无/不可用";
  const source = risk?.source_shock_bucket ? `${risk.source_shock_bucket}${typeof risk.shock_age === "number" ? ` · H${risk.shock_age}` : ""}` : "暂无/不可用";
  return <div className="entry-risk"><strong>{side === "long" ? "多头入场风险" : "空头入场风险"}</strong><span>联动：{linkage}</span><span>有效风险：{effective}</span><span>RSI 阈值：{rsi} · 杠杆：{leverage}</span>{risk?.source_shock_bucket && <span>来源：{source}</span>}</div>;
}

const entryWaitCopy: Record<string, string> = {
  completed_1h: "等待已完成的 1h K 线",
  price_outer_break_1h: "等待 1h 价格突破布林带外轨",
  rsi_threshold_1h: "等待 1h RSI 达到开仓阈值",
  bandwidth_guard: "正在检查 BandWidth 入场过滤",
  completed_5m: "等待已完成的 5m K 线",
  price_prev_extreme_break_5m: "等待 5m 价格突破上一根 K 线高／低点",
  entry_account_orderbook_guard: "等待进场与账户盘口确认",
  opened_protected: "等待开仓并建立保护止损",
};

function entryProgressLabel(view: Overview | null) {
  if (!view) return "数据暂未更新";
  if (view.entry_block_reason === "entry_unprotected") return "已开仓，等待保护止损恢复";
  const current = view.entry_steps.find((step) => step.state === "current");
  if (!current) return view.management_summary;
  if (current.id === "bandwidth_guard" && view.entry_block_reason) return `BandWidth 入场过滤阻止开仓：${view.entry_block_reason}`;
  return entryWaitCopy[current.id] ?? view.management_summary;
}

function trendProgressLabel(view: Overview | null) {
  if (!view?.trend_flow?.active) return "趋势信号状态：未知";
  const current = view.trend_flow.entry_steps.find((step) => step.state === "current") ?? view.trend_flow.management_steps.find((step) => step.state === "current");
  if (!current) return view.management_summary;
  return ({
    first_directional_exspecial: "等待首根定向 EXSPECIAL 信号",
    freeze_limit_price: "冻结收盘价 F 并计算回撤限价 L",
    trend_takeover_safety: "等待入场安全检查或反向均值回归接管清理",
    trend_gtc_pending: "固定价格 GTC 限价单等待成交",
    trend_opened_protected: "已成交，等待趋势保护止损确认",
    protective_stop: "趋势保护止损与水位跟踪中",
    weakening: "趋势弱化监测中",
    exit_cleanup: "等待确认仓位归零并清理保护止损",
  } as Record<string, string>)[current.id] ?? view.management_summary;
}

function TrendDiagram({ flow }: { flow?: Overview["trend_flow"] }) {
  return <>{!flow && <p className="flow-section-label">趋势信号状态：后端尚未提供</p>}<div className="vertical-flow">{trendEntrySteps.map(([id, title], index) => <Step key={id} title={`${index + 1}. ${title}`} state={flow ? itemState(flow.entry_steps, id) : "muted"} confirm={trendActionStepIds.has(id)} connector={index < trendEntrySteps.length - 1 ? (flow ? connectorState(flow.entry_connectors, id, trendEntrySteps[index + 1][0]) : "muted") : undefined} />)}</div><p className="flow-section-label">趋势止损与退出链</p><div className="vertical-flow">{trendManagementSteps.map(([id, title], index) => <Step key={id} title={title} state={flow ? itemState(flow.management_steps, id) : "muted"} confirm={trendActionStepIds.has(id)} connector={index < trendManagementSteps.length - 1 ? (flow ? connectorState(flow.management_connectors, id, trendManagementSteps[index + 1][0]) : "muted") : undefined} />)}</div></>;
}

const isTrendFlow = (value: unknown) => {
  const flow = value as { active?: unknown; mode?: unknown; entry_steps?: unknown; entry_connectors?: unknown; management_steps?: unknown; management_connectors?: unknown };
  return !!value && typeof value === "object" && typeof flow.active === "boolean" && ["off", "shadow", "live", "unknown"].includes(typeof flow.mode === "string" ? flow.mode : "") && isStepList(flow.entry_steps, trendEntrySteps.map(([id]) => id)) && isConnectorList(flow.entry_connectors, trendEntrySteps.map(([id]) => id)) && isStepList(flow.management_steps, trendManagementSteps.map(([id]) => id)) && isConnectorList(flow.management_connectors, trendManagementSteps.map(([id]) => id));
};

function normalize(value: unknown): Overview | null {
  if (!value || typeof value !== "object") return null;
  const view = value as Partial<Overview>;
  if (typeof view.symbol !== "string" || !isStepSet(view.entry_steps, entrySteps.map(([id]) => id)) || !isConnectorSet(view.entry_connectors, entrySteps.map(([id]) => id)) || !Array.isArray(view.branch_connectors) || !view.management_steps || !view.management_connectors || !view.runner || !view.bandwidth || !Array.isArray(view.updates)) return null;
  if (typeof view.bandwidth.status !== "string" || typeof view.bandwidth.allowed !== "boolean") return null;
  if (view.regime === "trend_riding") {
    if (!isTrendFlow(view.trend_flow)) return null;
  } else for (const lane of ["normal", "special", "exspecial"] as Regime[]) if (!isStepList(view.management_steps[lane], laneIds[lane]) || !isConnectorList(view.management_connectors[lane], laneIds[lane])) return null;
  return view as Overview;
}

export default function Home() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<Overview | null>(null);
  const [archives, setArchives] = useState<Archive[]>([]);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [stale, setStale] = useState(false);
  const [selectedFlow, setSelectedFlow] = useState<FlowKind>("mean_reversion");
  const inFlight = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/dashboard/overview", { cache: "no-store", signal: controller.signal }).then((response) => response.ok ? response.json() : null).then((value) => {
      const next = normalize(value);
      const configured = Array.isArray(value?.configured_symbols) ? value.configured_symbols.filter((symbol: unknown): symbol is string => typeof symbol === "string" && symbol.length > 0) : [];
      if (!next || !configured.length) return setStale(true);
      setSymbols(configured);
      setSelected((current) => current && configured.includes(current) ? current : configured[0]);
      setView(next);
      setStale(next.data_status !== "fresh");
    }).catch(() => setStale(true));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!selected) return;
    let active = true;
    const controller = new AbortController();
    const load = async () => {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        const response = await fetch(`/dashboard/overview?symbol=${selected}`, { cache: "no-store", signal: controller.signal });
        const next = normalize(await response.json());
        if (!response.ok || !next) throw new Error();
        if (active) { setView(next); setStale(next.data_status !== "fresh"); }
      } catch (error) {
        if (active && !(error instanceof DOMException && error.name === "AbortError")) setStale(true);
      } finally { inFlight.current = false; }
    };
    load();
    const timer = window.setInterval(load, 30000);
    return () => { active = false; controller.abort(); window.clearInterval(timer); };
  }, [selected]);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/dashboard/archives?limit=50", { cache: "no-store", signal: controller.signal }).then((response) => response.ok ? response.json() : { archives: [] }).then((value) => setArchives(Array.isArray(value.archives) ? value.archives : [])).catch(() => {});
    return () => controller.abort();
  }, []);

  const regime = view?.regime === "trend_riding" ? "normal" : view?.regime ?? "normal";
  const bandwidth = view?.bandwidth;
  const candidateRisk = view?.entry_risk;
  const hasCandidateRisk = candidateRisk?.slow_slope_state != null;
  const slopeState = (risk?: EntryRisk) => risk?.slow_slope_state ? (riskCopy[risk.slow_slope_state] ?? risk.slow_slope_state) : "—";
  const shouldAutoShowTrend = view?.position_source === "trend_riding" && view?.regime === "trend_riding";
  const showTrend = shouldAutoShowTrend || selectedFlow === "trend_riding";
  const managementStatus = showTrend ? "趋势骑行" : view?.position_source ? regime.toUpperCase() : "未持仓";
  const progressLabel = showTrend ? trendProgressLabel(view) : entryProgressLabel(view);
  return <main className="app-shell">
    <div className="runner-control"><span className={view?.runner.status === "running" ? "running" : "stopped"}>{runnerCopy[view?.runner.status ?? "unknown"]}</span></div>
    <div className="poll-updates"><p className="section-label">本轮轮询更新</p><pre>{view?.updates.length ? view.updates.join("\n") : "等待下一次轮询更新…"}</pre></div>
    <div className="workspace">
      <aside className="sidebar">
        <p className="section-label">监测币种</p>
        {symbols.map((symbol) => <button key={symbol} className={`symbol-row ${selected === symbol ? "selected" : ""}`} onClick={() => setSelected(symbol)}><b>{symbol}</b><span>{selected === symbol ? (view?.display_status ?? "数据暂未更新") : ""}</span></button>)}
        <div className="archive-dock"><button className="archive-toggle" onClick={() => setArchiveOpen(!archiveOpen)}>归档交易 <span>{archiveOpen ? "−" : "+"}</span></button>{archiveOpen && <div className="archive-list">{archives.map((trade) => <Link key={trade.id} href={`/archive/${trade.id}`}><b>{trade.symbol} {trade.side} · {formatPnl(trade.realized_pnl, trade.currency)} <em>{formatPct(trade.pnl_pct)}</em></b><small>北京时间 {formatBeijing(trade.closed_at)}</small></Link>)}</div>}</div>
      </aside>
      <section className="flow-area">
        {stale && <p className="data-notice">数据暂未更新</p>}
        <div className="flow-layout">
          <div className={`logic-diagram ${regime === "exspecial" && !showTrend ? "lockdown" : ""}`}>
            <div className="flow-tabs" aria-label="当前策略流水线"><button type="button" className={!showTrend ? "active" : ""} onClick={() => setSelectedFlow("mean_reversion")} disabled={shouldAutoShowTrend}>均值回归</button><button type="button" className={showTrend ? "active" : ""} onClick={() => setSelectedFlow("trend_riding")}>趋势骑行</button></div>
            {showTrend ? <TrendDiagram flow={view?.trend_flow} /> : <><div className="vertical-flow">{entrySteps.map(([id, title], index) => <Step key={id} title={`${index + 1}. ${title}`} state={view ? stepState(view, id) : "muted"} confirm={actionStepIds.has(id)} connector={index < entrySteps.length - 1 ? (view ? connectorState(view.entry_connectors, id, entrySteps[index + 1][0]) : "muted") : undefined} />)}</div><BranchDivider connectors={view?.branch_connectors} /><div className="regime-grid">{(["normal", "special", "exspecial"] as Regime[]).map((lane) => <section key={lane} className={`lane ${regime === lane ? "active" : "inactive"}`}><h2>{lane.toUpperCase()}</h2>{laneLabels[lane].map((title, index) => <Step key={title} title={title} state={view ? itemState(view.management_steps[lane], laneIds[lane][index]) : "muted"} confirm={actionStepIds.has(laneIds[lane][index])} connector={index < laneLabels[lane].length - 1 ? (view ? connectorState(view.management_connectors[lane], laneIds[lane][index], laneIds[lane][index + 1]) : "muted") : undefined} />)}</section>)}</div></>}
          </div>
          <aside className="context-tags">
            <p className="section-label">仓位管理状态</p><b className="status-tag">{managementStatus}</b>
            {!showTrend && <><div className="metric-card"><p>入场慢斜率</p><div className="metric-line"><span>多头</span><b>{slopeState(view?.entry_risks?.long)} · {ratio(view?.entry_risks?.long?.slow_slope_pct ?? null)}</b></div><div className="metric-line"><span>空头</span><b>{slopeState(view?.entry_risks?.short)} · {ratio(view?.entry_risks?.short?.slow_slope_pct ?? null)}</b></div></div>
            <div className="metric-card bandwidth-card">
              <p>BandWidth 原始过滤</p><div className="metric-head"><strong>{bandwidth?.status ?? "—"}</strong><b>{bandwidth?.allowed ? "原始过滤通过" : "原始过滤阻止"}</b></div>
              <div className="metric-line"><span>带宽值</span><b>{ratio(bandwidth?.raw ?? null)}</b></div>
              <div className="metric-compare"><span>120h 分位 <b>{rank(bandwidth?.percentile)}</b></span><span>警戒线 <b>{rank(bandwidth?.high_percentile)}</b></span></div>
              <div className="metric-compare"><span>1h 相对变化 <b>{ratio(bandwidth?.change_1h ?? null)}</b></span><span>急扩张线 <b>{ratio(bandwidth?.expansion_threshold ?? null)}</b></span></div>
              <div className="metric-line"><span>3h 相对变化</span><b>{ratio(bandwidth?.change_3h ?? null)}</b></div>
              {hasCandidateRisk && <div className="entry-risk"><strong>当前候选入场风险</strong><span>{candidateRisk?.allow ? "BandWidth 未阻止该候选" : `BandWidth 阻止：${candidateRisk?.reason ?? "不可用"}`}</span><span>联动：{riskCopy[candidateRisk?.linkage_state ?? "none"] ?? candidateRisk?.linkage_state}</span><span>有效风险：{riskCopy[candidateRisk?.effective_state ?? "normal"] ?? candidateRisk?.effective_state}</span></div>}
              <EntryRiskCard side="long" risk={view?.entry_risks?.long} /><EntryRiskCard side="short" risk={view?.entry_risks?.short} />
            </div></>}
            {showTrend && <div className="metric-card"><p>趋势骑行模式</p><div className="metric-line"><span>后端运行模式</span><b>{view?.trend_flow?.mode ?? "未知"}</b></div><div className="metric-line"><span>冻结该根 1h 收盘价 F</span><b>{price(view?.trend_flow?.frozen_1h_close)}</b></div><div className="metric-line"><span>计算限价 L</span><b>{price(view?.trend_flow?.limit_price)}</b></div></div>}
            <span className="tag">{progressLabel}</span>{view?.regime_transition && <span className="tag">状态切换：{view.regime_transition}</span>}{view?.position_tags.map((tag) => <span className="tag manual-tag" key={tag}>{tagCopy[tag] ?? tag}</span>)}
          </aside>
        </div>
      </section>
    </div>
  </main>;
}
