import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(new Request("http://localhost/", { headers: { accept: "text/html" } }), { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } }, { waitUntil() {}, passThroughOnException() {} });
}

test("server-renders the BBMR live-flow shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /读取已完成的 1h K 线/);
  assert.match(html, /5m 价格突破上一根 K 线高/);
  assert.match(html, /已开仓并建立保护止损/);
  assert.match(html, /滚动中轨目标随完成 1h 更新/);
});

test("uses read-only dashboard endpoints and keeps the visual contract", async () => {
  const [page, data, archive, overviewRoute] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/flow-data.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/archive/[id]/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/dashboard/overview/route.ts", import.meta.url), "utf8"),
  ]);
  assert.match(page, /confirm=\{actionStepIds\.has\(id\)\}/);
  assert.match(page, /actionStepIds\.has\(laneIds\[lane\]\[index\]\)/);
  assert.match(page, /BranchDivider/);
  assert.match(page, /branch_connectors/);
  assert.match(page, /className="metric-card"/);
  assert.match(page, /BandWidth 原始过滤/);
  assert.match(page, /BandWidth 入场过滤/);
  assert.match(page, /entryProgressLabel/);
  assert.match(page, /className="flow-tabs"/);
  assert.match(page, /setSelectedFlow\("mean_reversion"\)/);
  assert.match(page, /shouldAutoShowTrend/);
  assert.match(page, /setSelectedFlow\("trend_riding"\)/);
  assert.match(page, /趋势止损与退出链/);
  assert.match(page, /冻结该根 1h 收盘价 F/);
  assert.match(page, /计算限价 L/);
  assert.match(page, /frozen_1h_close/);
  assert.match(page, /limit_price/);
  assert.doesNotMatch(page, /BandWidth 仅保留为均值回归证据/);
  assert.match(page, /带宽值/);
  assert.match(page, /120h 分位/);
  assert.match(page, /1h 相对变化/);
  assert.match(page, /3h 相对变化/);
  assert.match(page, /\/ 100/);
  assert.match(page, /entry_risks/);
  assert.match(page, /bw_shock_block/);
  assert.match(page, /bw_continuation_special/);
  assert.match(page, /source_shock_bucket/);
  assert.match(page, /source_shock_bucket && <span>来源：\{source\}<\/span>/);
  assert.match(page, /H\$\{risk\.shock_age\}/);
  assert.match(page, /暂无\/不可用/);
  assert.match(page, /入场慢斜率/);
  assert.match(data, /completed_1h_available/);
  assert.match(page, /slopeState\(view\?\.entry_risks\?\.long\)/);
  assert.match(page, /slopeState\(view\?\.entry_risks\?\.short\)/);
  assert.match(page, /slow_slope_pct/);
  assert.match(page, /本轮轮询更新/);
  assert.match(page, /\? \(view \? connectorState\(view\.entry_connectors[\s\S]*: "muted"\) : undefined/);
  assert.match(page, /setInterval\(load,\s*30000\)/);
  assert.match(page, /isStepSet/);
  assert.match(page, /isConnectorSet/);
  assert.match(page, /\/dashboard\/overview/);
  assert.match(page, /configured_symbols/);
  assert.match(page, /setSymbols\(configured\)/);
  assert.doesNotMatch(page, /const symbols = \["BTC", "ETH", "SOL"\]/);
  assert.doesNotMatch(page, /demoOverviews/);
  assert.match(data, /5m 收盘到达下轨与中轨的中间位/);
  assert.match(data, /EntryRisk/);
  assert.match(data, /normal_risk_half_stop/);
  assert.match(data, /trend_riding/);
  assert.match(data, /first_directional_exspecial/);
  assert.match(data, /trend_opened_protected/);
  assert.ok(data.indexOf('"completed_5m"') < data.indexOf('"bandwidth_guard"'));
  assert.ok(data.indexOf('"price_prev_extreme_break_5m"') < data.indexOf('"bandwidth_guard"'));
  assert.match(archive, /\/dashboard\/archives\/\$\{id\}\/snapshot/);
  assert.match(archive, /DOMParser/);
  assert.match(archive, /ArchivedDiagram/);
  assert.match(archive, /archivedState/);
  assert.match(overviewRoute, /http:\/\/127\.0\.0\.1:8765/);
  assert.doesNotMatch(overviewRoute, /POST|sqlite|LiveStateStore/);
});

test("shows H0, H1, and H2 backend shock sources without linkage-specific filtering", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  for (const risk of [
    { linkage: "bw_shock_block", age: 0 },
    { linkage: "bw_continuation_special", age: 1 },
    { linkage: "bw_continuation_special", age: 2 },
  ]) {
    assert.match(page, new RegExp(risk.linkage));
    assert.match(`2026-01-01T00:00:00Z · H${risk.age}`, new RegExp(`H${risk.age}$`));
  }
  assert.match(page, /source_shock_bucket && <span>来源：\{source\}<\/span>/);
  assert.doesNotMatch(page, /linkage_state === "bw_continuation_special" && <span>来源/);
});
