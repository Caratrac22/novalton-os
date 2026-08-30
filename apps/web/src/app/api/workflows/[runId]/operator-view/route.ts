import { getApiBaseUrl, scopedApiPath } from "@/lib/api/config";
import { isUuid } from "@/lib/api/scoped";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ runId: string }> }): Promise<Response> {
  const { runId } = await context.params;
  if (!isUuid(runId)) return Response.json({ message: "Invalid workflow run." }, { status: 400 });
  try {
    const upstream = await fetch(`${getApiBaseUrl()}${scopedApiPath(`workflow-runs/${runId}/operator-view`)}`, { cache: "no-store", headers: { Accept: "application/json" }, signal: AbortSignal.timeout(5000) });
    if (!upstream.ok) return Response.json({ message: "The operator view is unavailable." }, { status: upstream.status });
    return Response.json(await upstream.json());
  } catch { return Response.json({ message: "The operator view is unavailable." }, { status: 503 }); }
}
