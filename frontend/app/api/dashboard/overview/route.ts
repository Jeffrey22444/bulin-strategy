import { NextRequest } from "next/server";

const origin = process.env.BBMR_DASHBOARD_API_URL ?? "http://127.0.0.1:8765";

export async function GET(request: NextRequest) {
  const upstream = await fetch(`${origin}/api/dashboard/overview${request.nextUrl.search}`, { cache: "no-store" });
  return new Response(await upstream.arrayBuffer(), { status: upstream.status, headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" } });
}
