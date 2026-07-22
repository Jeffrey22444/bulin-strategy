"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { actionStepIds, Archive, connectorState, entrySteps, formatBeijing, formatPct, formatPnl, itemState, laneIds, laneLabels, Regime, StepState } from "../../flow-data";

type ArchivedFlow = { regime: Regime; entry_steps: { id: string; state: StepState }[]; entry_connectors: { from: string; to: string; state: StepState }[]; branch_connectors: { from: string; to: string; state: StepState }[]; management_steps: Record<Regime, { id: string; state: StepState }[]>; management_connectors: Record<Regime, { from: string; to: string; state: StepState }[]>; };

const isState = (value: unknown): value is StepState => value === "passed" || value === "current" || value === "muted";
const validSteps = (value: unknown, ids: readonly string[]) => Array.isArray(value) && value.length === ids.length && value.every((step, index) => !!step && typeof step === "object" && (step as { id?: unknown }).id === ids[index] && isState((step as { state?: unknown }).state));
const validConnectors = (value: unknown, ids: readonly string[]) => Array.isArray(value) && value.length === ids.length - 1 && value.every((connector, index) => !!connector && typeof connector === "object" && (connector as { from?: unknown }).from === ids[index] && (connector as { to?: unknown }).to === ids[index + 1] && isState((connector as { state?: unknown }).state));
const archivedState = (state: StepState): StepState => state === "muted" ? "muted" : "passed";

function parseSnapshot(svg: string): ArchivedFlow | null {
  try {
    const document = new DOMParser().parseFromString(svg, "image/svg+xml");
    const value = JSON.parse(document.querySelector("metadata")?.textContent ?? "") as Partial<ArchivedFlow>;
    if (!(["normal", "special", "exspecial"] as string[]).includes(value.regime ?? "") || !validSteps(value.entry_steps, entrySteps.map(([id]) => id)) || !validConnectors(value.entry_connectors, entrySteps.map(([id]) => id))) return null;
    for (const lane of ["normal", "special", "exspecial"] as Regime[]) if (!validSteps(value.management_steps?.[lane], laneIds[lane]) || !validConnectors(value.management_connectors?.[lane], laneIds[lane])) return null;
    return value as ArchivedFlow;
  } catch { return null; }
}

function ArchivedStep({ title, state, connector, action = false }: { title: string; state: StepState; connector?: StepState; action?: boolean }) {
  return <><div className={`step ${archivedState(state)} ${action ? "confirm" : ""}`}><span className="node-dot" /><strong>{title}</strong></div>{connector !== undefined && <div className={`connector ${archivedState(connector)}`} />}</>;
}

function ArchiveBranch({ connectors }: { connectors: ArchivedFlow["branch_connectors"] }) {
  return <div className="branch-connector" aria-label="归档仓位管理分支连接">{(["normal", "special", "exspecial"] as Regime[]).map((lane) => <span key={lane} className={archivedState(connectorState(connectors, "opened_protected", lane))} />)}</div>;
}

function ArchivedDiagram({ flow }: { flow: ArchivedFlow }) {
  return <div className="archive-diagram logic-diagram"><div className="vertical-flow">{entrySteps.map(([id, title], index) => <ArchivedStep key={id} title={`${index + 1}. ${title}`} state={itemState(flow.entry_steps, id)} action={actionStepIds.has(id)} connector={index < entrySteps.length - 1 ? connectorState(flow.entry_connectors, id, entrySteps[index + 1][0]) : undefined} />)}</div><ArchiveBranch connectors={flow.branch_connectors} /><div className="regime-grid">{(["normal", "special", "exspecial"] as Regime[]).map((lane) => <section key={lane} className={`lane ${flow.regime === lane ? "active" : "inactive"}`}><h2>{lane.toUpperCase()}</h2>{laneLabels[lane].map((title, index) => <ArchivedStep key={title} title={title} state={itemState(flow.management_steps[lane], laneIds[lane][index])} action={actionStepIds.has(laneIds[lane][index])} connector={index < laneLabels[lane].length - 1 ? connectorState(flow.management_connectors[lane], laneIds[lane][index], laneIds[lane][index + 1]) : undefined} />)}</section>)}</div></div>;
}

export default function ArchivePage() {
  const { id } = useParams<{ id: string }>();
  const [trade, setTrade] = useState<Archive | null>(null);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [flow, setFlow] = useState<ArchivedFlow | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/dashboard/archives/${id}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const value = response.ok ? await response.json() : null;
        if (!value?.snapshot_available) return { trade: value, flow: null };
        const snapshot = await fetch(`/dashboard/archives/${id}/snapshot`, { cache: "no-store", signal: controller.signal });
        return { trade: value, flow: snapshot.ok ? parseSnapshot(await snapshot.text()) : null };
      })
      .then((value) => { setTrade(value?.trade ?? null); setAvailable(value?.trade?.snapshot_available === true); setFlow(value?.flow ?? null); })
      .catch(() => { if (!controller.signal.aborted) setAvailable(false); });
    return () => controller.abort();
  }, [id]);

  return <main className="app-shell"><header className="topbar"><div><p className="eyebrow">ARCHIVED FLOW SNAPSHOT</p><h1>{trade ? `${trade.symbol} ${trade.side} · 流水线快照` : "归档流水线快照"}</h1>{trade && <p className="subtle">北京时间 {formatBeijing(trade.closed_at)} · {formatPnl(trade.realized_pnl, trade.currency)} · {formatPct(trade.pnl_pct)}</p>}</div><Link className="back-link" href="/">返回实时链路</Link></header><section className="snapshot"><p className="section-label">归档时保存的最终路径</p>{flow ? <ArchivedDiagram flow={flow} /> : available === true ? <img className="snapshot-image" src={`/dashboard/archives/${id}/snapshot`} alt="归档时保存的流水线快照" /> : available === false ? <p className="snapshot-unavailable">此归档交易没有可用快照。</p> : <p className="snapshot-unavailable">正在读取归档快照…</p>}</section></main>;
}
