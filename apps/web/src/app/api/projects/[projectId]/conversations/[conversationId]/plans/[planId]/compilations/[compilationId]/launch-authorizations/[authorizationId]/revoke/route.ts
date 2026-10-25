import { scopedSessionFetch, isRecord, isUuid } from "@/lib/api/scoped";
import { verifiedMutationOrigin } from "@/lib/operator-origin";

type Context = { params: Promise<{ projectId: string; conversationId: string; planId: string; compilationId: string; authorizationId: string }> };

export async function POST(request: Request, { params }: Context) {
  if (!verifiedMutationOrigin(request)) return new Response("Accès refusé", { status: 403 });
  const { projectId, conversationId, planId, compilationId, authorizationId } = await params;
  if (![projectId, conversationId, planId, compilationId, authorizationId].every(isUuid))
    return new Response("Autorisation invalide", { status: 400 });
  let data: unknown;
  try { data = await request.json(); } catch { return new Response("Saisie invalide", { status: 400 }); }
  if (!isRecord(data) || typeof data.current_password !== "string" || data.current_password.length < 1)
    return new Response("Mot de passe requis", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(
      `projects/${projectId}/conversations/${conversationId}/plans/${planId}/compilations/${compilationId}/launch-authorizations/${authorizationId}/revoke`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password: data.current_password }) },
    );
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
