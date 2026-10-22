import { verifiedMutationOrigin } from "@/lib/operator-origin";
import { postWorkflow } from "@/lib/api/workflows";
import { isUuid } from "@/lib/api/scoped";

export const dynamic = "force-dynamic";

export async function POST(request: Request, context: { params: Promise<{ runId: string }> }): Promise<Response> {
  if (!verifiedMutationOrigin(request)) return new Response("Forbidden", { status: 403 });
  const { runId } = await context.params;
  if (!isUuid(runId)) return Response.json({ message: "Invalid workflow run." }, { status: 400 });
  try {
    const response = await postWorkflow(`workflow-runs/${runId}/advance`);
    if (!response.ok) return Response.json({ message: response.status === 409 ? "The workflow state changed. Refresh and review the current state." : "The workflow could not be advanced." }, { status: response.status });
    return Response.json(await response.json());
  } catch { return Response.json({ message: "The workflow service is unavailable." }, { status: 503 }); }
}
