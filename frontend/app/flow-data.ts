export type Regime = "normal" | "special" | "exspecial";
export type FlowKind = "mean_reversion" | "trend_riding";
export type StepState = "passed" | "current" | "muted";
export type EntryRisk = { slow_slope_state?: string | null; slow_slope_pct?: number | null; linkage_state?: string | null; effective_state?: string | null; rsi_threshold?: number | null; leverage?: number | null; allow?: boolean | null; reason?: string | null; source_shock_bucket?: string | null; shock_age?: number | null; shock_direction?: string | null };

export const entrySteps = [
  ["completed_1h", "读取已完成的 1h K 线"],
  ["price_outer_break_1h", "1h 价格突破布林带外轨"],
  ["rsi_threshold_1h", "1h RSI 达到开仓阈值"],
  ["completed_5m", "读取已完成的 5m K 线"],
  ["price_prev_extreme_break_5m", "5m 价格突破上一根 K 线高／低点"],
  ["bandwidth_guard", "BandWidth 入场过滤"],
  ["entry_account_orderbook_guard", "进场与账户盘口确认"],
  ["opened_protected", "已开仓并建立保护止损"],
] as const;

export const laneLabels = {
  normal: ["5m 收盘到达下轨与中轨的中间位", "保护止损调整为风险减半", "5m 收盘穿过 1h 中轨", "保护止损调整为开仓价", "5m 高／低价到达中轨与外轨的中间位", "保护止损跟随至最新完成 1h 中轨", "5m 高／低价突破 1h 外轨", "保护止损调整为当前 5m 收盘价"],
  special: ["当前价格进入 SPECIAL 管理", "当前保护止损继续运行", "滚动中轨目标随完成 1h 更新", "当前价格触及滚动中轨目标", "触发平仓并确认仓位归零"],
  exspecial: ["当前价格进入 EXSPECIAL", "冻结当前保护止损价格", "滚动半带防御目标随完成 1h 更新", "当前价格触及半带防御目标", "触发平仓并确认仓位归零"],
} as const;

export const laneIds = {
  normal: ["normal_midpoint_condition", "normal_risk_half_stop", "normal_middle_cross_condition", "normal_breakeven_stop", "normal_halfband_condition", "normal_midband_follow_stop", "normal_outer_break_condition", "normal_outer_close_stop"],
  special: ["special_regime_active", "special_protective_stop_active", "special_target_tracking", "special_target_reached", "special_close_confirmed"],
  exspecial: ["exspecial_regime_active", "exspecial_stop_frozen", "exspecial_target_tracking", "exspecial_target_reached", "exspecial_close_confirmed"],
} as const;

export const trendEntrySteps = [
  ["first_directional_exspecial", "首根定向 EXSPECIAL 已确认"],
  ["freeze_limit_price", "冻结该根 1h 收盘价并计算限价 L"],
  ["trend_takeover_safety", "入场安全检查／反向均值回归接管清理"],
  ["trend_gtc_pending", "固定价格 GTC 限价单等待成交"],
  ["trend_opened_protected", "已成交并建立趋势保护止损"],
] as const;

export const trendManagementSteps = [
  ["protective_stop", "保护止损持续有效"],
  ["water_mark", "完成 1h 收盘更新有利水位与止损候选"],
  ["break_even", "完成 1h 收盘突破外轨后止损至少到开仓价"],
  ["weakening", "趋势弱化监测"],
  ["middle_cross", "弱化后完成 1h 收盘反向穿越中轨则市价平仓"],
  ["normal_fallback", "趋势强度回落至 NORMAL 则市价平仓"],
  ["exit_cleanup", "确认仓位归零后清理保护止损"],
] as const;

/** Actions change protection/target/position; all other nodes are trigger conditions. */
export const actionStepIds = new Set([
  "opened_protected",
  "normal_risk_half_stop", "normal_breakeven_stop", "normal_midband_follow_stop", "normal_outer_close_stop",
  "special_protective_stop_active", "special_target_tracking", "special_close_confirmed",
  "exspecial_stop_frozen", "exspecial_target_tracking", "exspecial_close_confirmed",
  "freeze_limit_price", "trend_gtc_pending", "trend_opened_protected", "water_mark", "break_even", "middle_cross", "normal_fallback", "exit_cleanup",
]);

export const trendActionStepIds = new Set([
  "freeze_limit_price", "trend_gtc_pending", "trend_opened_protected", "water_mark", "break_even", "middle_cross", "normal_fallback", "exit_cleanup",
]);

export type Overview = {
  symbol: string;
  display_status: string;
  regime: Regime | "trend_riding";
  completed_1h_available: boolean;
  completed_1h_slope_pct: number | null;
  slope_quality: "valid" | "fallback" | "unavailable";
  bandwidth: { status: string; allowed: boolean; reason: string | null; raw: number | null; percentile: number | null; change_1h: number | null; change_3h: number | null; high_percentile: number; percentile_distance: number | null; expansion_threshold: number; expansion_distance: number | null };
  /** Backend-authoritative risk for the active 1h candidate; null fields mean no candidate. */
  entry_risk?: EntryRisk;
  entry_risks?: { long?: EntryRisk; short?: EntryRisk };
  updates: string[];
  data_status: "fresh" | "stale" | "unavailable";
  entry_allowed: boolean;
  entry_block_reason: string | null;
  position_tags: string[];
  position_source: "strategy" | "manual_adopted" | "trend_riding" | null;
  regime_transition: string | null;
  entry_steps: { id: string; state: StepState }[];
  entry_connectors: { from: string; to: string; state: StepState }[];
  branch_connectors: { from: string; to: string; state: StepState }[];
  management_steps: Partial<Record<Regime | "trend_riding", { id?: string; state: StepState }[]>>;
  management_connectors: Partial<Record<Regime | "trend_riding", { from: string; to: string; state: StepState }[]>>;
  management_summary: string;
  trend_flow?: {
    active: boolean;
    mode: "off" | "shadow" | "live" | "unknown";
    /** Frozen by the runner from the qualifying completed 1h candle; null means unavailable. */
    frozen_1h_close?: number | null;
    /** Runner-calculated fixed trend-entry limit L; null means unavailable. */
    limit_price?: number | null;
    entry_steps: { id: string; state: StepState }[];
    entry_connectors: { from: string; to: string; state: StepState }[];
    management_steps: { id: string; state: StepState }[];
    management_connectors: { from: string; to: string; state: StepState }[];
  };
  runner: { status: "starting" | "running" | "stopped" | "error" | "unknown" };
};

export type Archive = { id: string; symbol: string; side: string; closed_at: string | null; realized_pnl: number | null; currency: string; pnl_pct: number | null; snapshot_available: boolean };

export function stepState(overview: Overview, id: string): StepState {
  return overview.entry_steps.find((step) => step.id === id)?.state ?? "muted";
}

export function itemState(items: { id?: string; state: StepState }[], id: string): StepState {
  return items.find((item) => item.id === id)?.state ?? "muted";
}

export function connectorState(items: { from: string; to: string; state: StepState }[], from: string, to: string): StepState { return items.find((item) => item.from === from && item.to === to)?.state ?? "muted"; }

export function formatPnl(value: number | null, currency: string) {
  return value === null ? "—" : `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(2)} ${currency}`;
}

export function formatPct(value: number | null) {
  return value === null ? "—" : `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(2)}%`;
}

export function formatBeijing(value: string | null) {
  return value ? new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)).replace(/\//g, "-") : "北京时间 —";
}
