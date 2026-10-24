import { scopedSessionFetch, isUuid, isRecord } from "@/lib/api/scoped";
import { verifiedMutationOrigin } from "@/lib/operator-origin";
type Context = { params: Promise<{ projectId: string; conversationId: string }> };
async function path(context: Context) {
  const { projectId, conversationId } = await context.params;
  return isUuid(projectId) && isUuid(conversationId) ? `projects/${projectId}/conversations/${conversationId}/plans` : null;
}
export async function GET(_request: Request, context: Context) {
  const target = await path(context);
  if (!target) return new Response("Conversation invalide", { status: 400 });
  try { const upstream = await scopedSessionFetch(target); return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } }); }
  catch { return new Response("Service indisponible", { status: 503 }); }
}
export async function POST(request: Request, context: Context) {
  if (!verifiedMutationOrigin(request)) return new Response("Accès refusé", { status: 403 });
  const target = await path(context);
  if (!target) return new Response("Conversation invalide", { status: 400 });
  let data: unknown;
  try { data = await request.json(); } catch { return new Response("Saisie invalide", { status: 400 }); }
  if (!isRecord(data) || !Number.isSafeInteger(data.expected_specification_version) || (data.expected_specification_version as number) < 1) return new Response("Version invalide", { status: 400 });
  try { const upstream = await scopedSessionFetch(target, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }); return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } }); }
  catch { return new Response("Service indisponible", { status: 503 }); }
}
