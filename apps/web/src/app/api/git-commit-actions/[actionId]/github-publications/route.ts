import { getApiBaseUrl, scopedApiPath } from "@/lib/api/config";
import { isRecord, isUuid } from "@/lib/api/scoped";

export async function POST(request: Request, context: { params: Promise<{ actionId: string }> }): Promise<Response> {
  const { actionId } = await context.params;
  if (!isUuid(actionId)) return Response.json({ message: "Invalid commit action." }, { status: 400 });
  let body: unknown;
  try { body = await request.json(); } catch { return Response.json({ message: "Enter a PR title and body." }, { status: 400 }); }
  if (!isRecord(body) || typeof body.title !== "string" || typeof body.body !== "string" || body.title.length < 1 || body.title.length > 160 || body.body.length > 16384) return Response.json({ message: "PR title/body is outside the safe bound." }, { status: 400 });
  try { const upstream = await fetch(`${getApiBaseUrl()}${scopedApiPath(`git-commit-actions/${actionId}/github-publications`)}`, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ title: body.title, body: body.body }), signal: AbortSignal.timeout(15000) }); return Response.json(await upstream.json(), { status: upstream.status }); } catch { return Response.json({ message: "The publication service is unavailable." }, { status: 503 }); }
}
