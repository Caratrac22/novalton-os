import { verifiedMutationOrigin } from "@/lib/operator-origin";
import { NextResponse } from "next/server";
import { scopedSessionFetch } from "@/lib/api/scoped";

type Context = { params: Promise<{ runId: string }> };

export async function GET(_: Request, { params }: Context) {
  const { runId } = await params;
  const upstream = await scopedSessionFetch(`workflow-runs/${runId}/git-commit-actions`, { cache: "no-store", headers: { Accept: "application/json" }, signal: AbortSignal.timeout(5000) });
  return new NextResponse(await upstream.text(), { status: upstream.status, headers: { "Content-Type": upstream.headers.get("Content-Type") || "application/json" } });
}

export async function POST(request: Request, { params }: Context) {
  if (!verifiedMutationOrigin(request)) return new Response("Forbidden", { status: 403 });
  const { runId } = await params;
  const body = await request.json();
  const upstream = await scopedSessionFetch(`workflow-runs/${runId}/git-commit-actions`, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ commit_message: body?.commit_message }), signal: AbortSignal.timeout(15000) });
  return new NextResponse(await upstream.text(), { status: upstream.status, headers: { "Content-Type": upstream.headers.get("Content-Type") || "application/json" } });
}
