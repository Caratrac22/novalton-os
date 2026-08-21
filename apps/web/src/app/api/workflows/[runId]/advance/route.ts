import { postWorkflow } from "@/lib/api/workflows";
import { isUuid } from "@/lib/api/scoped";

export const dynamic = "force-dynamic";

export async function POST(_request: Request, context: { params: Promise<{ runId: string }> }): Promise<Response> {
  const { runId } = await context.params;
  if (!isUuid(runId)) return Response.json({ message: "Invalid workflow run." }, { status: 400 });
  const response = await postWorkflow(`workflow-runs/${runId}/advance`);
  if (!response.ok) return Response.json({ message: response.status === 409 ? "The workflow state changed. Refresh and review the current state." : "The workflow could not be advanced." }, { status: response.status });
  return Response.json(await response.json());
}
