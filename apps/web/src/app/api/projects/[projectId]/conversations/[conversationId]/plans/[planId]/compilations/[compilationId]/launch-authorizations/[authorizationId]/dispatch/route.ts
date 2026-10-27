import { scopedSessionFetch, isRecord, isUuid } from "@/lib/api/scoped";
import { verifiedMutationOrigin } from "@/lib/operator-origin";

type Context = { params: Promise<{ projectId: string; conversationId: string; planId: string; compilationId: string; authorizationId: string }> };
function destination(ids: Awaited<Context["params"]>) {
  if (!Object.values(ids).every(isUuid)) return null;
  const { projectId, conversationId, planId, compilationId, authorizationId } = ids;
  return `projects/${projectId}/conversations/${conversationId}/plans/${planId}/compilations/${compilationId}/launch-authorizations/${authorizationId}/dispatch`;
}

export async function GET(_request: Request, { params }: Context) {
  const path = destination(await params);
  if (!path) return new Response("Autorisation invalide", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(path);
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}

export async function POST(request: Request, { params }: Context) {
  if (!verifiedMutationOrigin(request)) return new Response("Accès refusé", { status: 403 });
  const path = destination(await params);
  if (!path) return new Response("Autorisation invalide", { status: 400 });
  let data: unknown;
  try { data = await request.json(); } catch { return new Response("Saisie invalide", { status: 400 }); }
  if (!isRecord(data) || data.confirmation !== "ENQUEUE_DISPOSABLE_TEST_WORKFLOW" || !isUuid(data.request_id) ||
    typeof data.current_password !== "string" || data.current_password.length < 1)
    return new Response("Lancement invalide", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(path,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
