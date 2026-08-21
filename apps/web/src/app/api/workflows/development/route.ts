import { postWorkflow } from "@/lib/api/workflows";
import { isRecord, isUuid } from "@/lib/api/scoped";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  let body: unknown;
  try { body = await request.json(); } catch { return Response.json({ message: "Enter an objective and at least one acceptance criterion." }, { status: 400 }); }
  if (!isRecord(body) || !isUuid(body.projectId) || !isUuid(body.taskId) || typeof body.objective !== "string" || !Array.isArray(body.acceptanceCriteria) || body.acceptanceCriteria.length < 1 || body.acceptanceCriteria.some((item) => typeof item !== "string")) return Response.json({ message: "The workflow request is incomplete." }, { status: 400 });
  const response = await postWorkflow(`projects/${body.projectId}/tasks/${body.taskId}/development-workflows`, { objective: body.objective, acceptance_criteria: body.acceptanceCriteria });
  if (!response.ok) return Response.json({ message: response.status === 409 ? "The governed development agents are unavailable right now." : "The development workflow could not be created." }, { status: response.status });
  return Response.json(await response.json());
}
