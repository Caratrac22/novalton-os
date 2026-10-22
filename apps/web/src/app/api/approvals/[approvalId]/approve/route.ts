import { verifiedMutationOrigin } from "@/lib/operator-origin";
import { scopedSessionFetch } from "@/lib/api/scoped";
import { isUuid } from "@/lib/api/scoped";

export async function POST(request: Request, context: { params: Promise<{ approvalId: string }> }): Promise<Response> {
  if (!verifiedMutationOrigin(request)) return new Response("Forbidden", { status: 403 });
  const { approvalId } = await context.params;
  if (!isUuid(approvalId)) return Response.json({ message: "Invalid approval request." }, { status: 400 });
  try {
    const upstream = await scopedSessionFetch(`approvals/${approvalId}/approve`, { method: "POST", headers: { Accept: "application/json" }, signal: AbortSignal.timeout(120000) });
    return Response.json(await upstream.json(), { status: upstream.status });
  } catch { return Response.json({ message: "The approval request is unavailable." }, { status: 503 }); }
}
