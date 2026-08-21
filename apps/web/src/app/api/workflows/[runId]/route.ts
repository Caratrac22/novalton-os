import { getApiBaseUrl, scopedApiPath } from "@/lib/api/config";
import { isUuid } from "@/lib/api/scoped";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ runId: string }> }): Promise<Response> {
  const { runId } = await context.params;
  if (!isUuid(runId)) return Response.json({ message: "Invalid workflow run." }, { status: 400 });
  try {
    const response = await fetch(`${getApiBaseUrl()}${scopedApiPath(`workflow-runs/${runId}`)}`, { cache: "no-store", headers: { Accept: "application/json" }, signal: AbortSignal.timeout(5000) });
    if (!response.ok) return Response.json({ message: "The workflow state is unavailable." }, { status: response.status });
    return Response.json(await response.json());
  } catch { return Response.json({ message: "The workflow state is unavailable." }, { status: 503 }); }
}
