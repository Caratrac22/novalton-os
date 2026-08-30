import { getApiBaseUrl, scopedApiPath } from "@/lib/api/config";
import { isRecord, isUuid } from "@/lib/api/scoped";

export const dynamic = "force-dynamic";

export async function POST(request: Request, context: { params: Promise<{ projectId: string }> }): Promise<Response> {
  const { projectId } = await context.params;
  if (!isUuid(projectId)) return Response.json({ message: "Invalid project selection." }, { status: 400 });
  let body: unknown;
  try { body = await request.json(); } catch { return Response.json({ message: "Enter a task objective." }, { status: 400 }); }
  if (!isRecord(body) || typeof body.title !== "string" || !(body.description === null || typeof body.description === "string")) return Response.json({ message: "The task request is incomplete." }, { status: 400 });
  try {
    const upstream = await fetch(`${getApiBaseUrl()}${scopedApiPath(`projects/${projectId}/tasks`)}`, { method: "POST", cache: "no-store", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ title: body.title, description: body.description, status: "READY" }), signal: AbortSignal.timeout(5000) });
    if (!upstream.ok) return Response.json({ message: "The task could not be created." }, { status: upstream.status });
    return Response.json(await upstream.json(), { status: 201 });
  } catch { return Response.json({ message: "The task service is unavailable." }, { status: 503 }); }
}
