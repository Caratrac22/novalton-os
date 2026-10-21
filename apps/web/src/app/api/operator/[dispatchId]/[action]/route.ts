import { dispatchUpstream } from "@/lib/api/dispatch";
import { verifiedMutationOrigin } from "@/lib/operator-origin";
import { isUuid } from "@/lib/api/scoped";

export async function POST(request: Request, context: { params: Promise<{ dispatchId: string; action: string }> }) {
  const { dispatchId, action } = await context.params;
  if (!verifiedMutationOrigin(request)) return Response.json({ message: "Origin unavailable" }, { status: 403 });
  if (!isUuid(dispatchId) || !["cancel", "resolve"].includes(action)) return Response.json({ message: "Invalid decision" }, { status: 400 });
  let body: unknown;
  try { body = await request.json(); } catch { return Response.json({ message: "Invalid decision" }, { status: 400 }); }
  if (!body || typeof body !== "object" || Array.isArray(body)) return Response.json({ message: "Invalid decision" }, { status: 400 });
  const input = body as Record<string, unknown>;
  if (action === "cancel" && Object.keys(input).length !== 0) return Response.json({ message: "Invalid decision" }, { status: 400 });
  if (action === "resolve" && (
    Object.keys(input).sort().join(",") !== "deadline,max_model_calls,request_key,workflow_run_id" ||
    !isUuid(input.workflow_run_id) || typeof input.request_key !== "string" ||
    !/^[a-zA-Z0-9_.:-]{1,128}$/.test(input.request_key) ||
    typeof input.deadline !== "string" || !Number.isFinite(Date.parse(input.deadline)) ||
    !Number.isInteger(input.max_model_calls) || (input.max_model_calls as number) < 0 ||
    (input.max_model_calls as number) > 128
  )) return Response.json({ message: "Invalid decision" }, { status: 400 });
  const upstream = await dispatchUpstream(`requests/${dispatchId}/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!upstream) return Response.json({ message: "Operator session unavailable" }, { status: 503 });
  if (!upstream.ok) return Response.json({ message: "Decision denied" }, { status: upstream.status });
  return Response.json(await upstream.json());
}
