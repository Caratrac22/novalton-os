import { postWorkflow } from "@/lib/api/workflows";
import { isRecord, isUuid } from "@/lib/api/scoped";

export const dynamic = "force-dynamic";

export async function POST(request: Request, context: { params: Promise<{ runId: string; stepRunId: string }> }): Promise<Response> {
  const { runId, stepRunId } = await context.params;
  if (!isUuid(runId) || !isUuid(stepRunId)) return Response.json({ message: "Invalid challenge selection." }, { status: 400 });
  let body: unknown;
  try { body = await request.json(); } catch { return Response.json({ message: "Choose a challenge decision." }, { status: 400 }); }
  if (!isRecord(body) || !["ACCEPT_RESULT", "REJECT_RESULT"].includes(String(body.decision)) || !(body.reason === null || typeof body.reason === "string") || Object.keys(body).some((key) => !["decision", "reason"].includes(key))) return Response.json({ message: "The challenge decision is invalid." }, { status: 400 });
  try {
    const upstream = await postWorkflow(`workflow-runs/${runId}/steps/${stepRunId}/challenge-resolution`, { decision: body.decision, reason: body.reason });
    if (!upstream.ok) return Response.json({ message: upstream.status === 409 ? "The challenge state changed. Refresh and review the current state." : "The challenge could not be resolved." }, { status: upstream.status });
    return Response.json(await upstream.json());
  } catch { return Response.json({ message: "The challenge service is unavailable." }, { status: 503 }); }
}
