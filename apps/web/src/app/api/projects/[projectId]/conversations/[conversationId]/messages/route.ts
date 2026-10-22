import { scopedSessionFetch, isUuid, isRecord } from "@/lib/api/scoped";
import { verifiedMutationOrigin } from "@/lib/operator-origin";
type Context = { params: Promise<{ projectId: string; conversationId: string }> };
function ids(projectId: string, conversationId: string): boolean { return isUuid(projectId) && isUuid(conversationId); }
export async function GET(request: Request, { params }: Context) {
  const { projectId, conversationId } = await params;
  if (!ids(projectId, conversationId)) return new Response("Conversation invalide", { status: 400 });
  const after = new URL(request.url).searchParams.get("after") ?? "0";
  if (!/^(0|[1-9]\d{0,6})$/.test(after)) return new Response("Page invalide", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(`projects/${projectId}/conversations/${conversationId}/messages?after=${after}&limit=50`);
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
export async function POST(request: Request, { params }: Context) {
  if (!verifiedMutationOrigin(request)) return new Response("Accès refusé", { status: 403 });
  const { projectId, conversationId } = await params;
  if (!ids(projectId, conversationId)) return new Response("Conversation invalide", { status: 400 });
  let body: unknown;
  try { body = await request.json(); } catch { return new Response("Message invalide", { status: 400 }); }
  if (!isRecord(body) || typeof body.content !== "string" || !body.content.trim() || body.content.length > 4000 || !isUuid(body.client_request_id)) return new Response("Message invalide", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(`projects/${projectId}/conversations/${conversationId}/messages`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      signal: AbortSignal.timeout(60000),
    });
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
