import { getApiBaseUrl, scopedApiPath } from "@/lib/api/config";
import { isUuid } from "@/lib/api/scoped";

export async function POST(_request: Request, context: { params: Promise<{ approvalId: string }> }): Promise<Response> {
  const { approvalId } = await context.params;
  if (!isUuid(approvalId)) return Response.json({ message: "Invalid approval request." }, { status: 400 });
  try {
    const upstream = await fetch(`${getApiBaseUrl()}${scopedApiPath(`approvals/${approvalId}/reject`)}`, { method: "POST", headers: { Accept: "application/json" }, signal: AbortSignal.timeout(5000) });
    return Response.json(await upstream.json(), { status: upstream.status });
  } catch { return Response.json({ message: "The approval request is unavailable." }, { status: 503 }); }
}
