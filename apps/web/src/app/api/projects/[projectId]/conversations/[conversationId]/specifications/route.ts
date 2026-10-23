import { scopedSessionFetch, isUuid, isRecord } from "@/lib/api/scoped";
import { verifiedMutationOrigin } from "@/lib/operator-origin";

type Context = { params: Promise<{ projectId: string; conversationId: string }> };
async function endpoint(context: Context) {
  const { projectId, conversationId } = await context.params;
  if (!isUuid(projectId) || !isUuid(conversationId)) return null;
  return `projects/${projectId}/conversations/${conversationId}/specifications`;
}
export async function GET(request: Request, context: Context) {
  const path = await endpoint(context);
  if (!path) return new Response("Conversation invalide", { status: 400 });
  const offset = new URL(request.url).searchParams.get("offset") ?? "0";
  if (!/^(0|[1-9]\d{0,5})$/.test(offset)) return new Response("Page invalide", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(`${path}?limit=20&offset=${offset}`);
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
export async function PUT(request: Request, context: Context) {
  if (!verifiedMutationOrigin(request)) return new Response("Accès refusé", { status: 403 });
  const path = await endpoint(context);
  if (!path) return new Response("Conversation invalide", { status: 400 });
  let body: unknown;
  try { body = await request.json(); } catch { return new Response("Saisie invalide", { status: 400 }); }
  if (!isRecord(body) || !Number.isSafeInteger(body.expected_version) || (body.expected_version as number) < 0 ||
      typeof body.summary !== "string" || body.summary.length > 3000 || !Array.isArray(body.items) || body.items.length > 100)
    return new Response("Cahier des charges invalide", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
