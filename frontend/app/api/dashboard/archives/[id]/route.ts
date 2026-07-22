import { NextRequest } from "next/server";

const origin = process.env.BBMR_DASHBOARD_API_URL ?? "http://127.0.0.1:8765";
const idPattern = /^[0-9a-f-]{36}$/;

export async function GET(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!idPattern.test(id)) return Response.json({ error: "not_found" }, { status: 404 });
  const upstream = await fetch(`${origin}/api/dashboard/archives/${id}`, { cache: "no-store" });
  return new Response(await upstream.arrayBuffer(), { status: upstream.status, headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" } });
}
