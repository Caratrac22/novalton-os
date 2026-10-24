import { scopedSessionFetch, isUuid, isRecord } from "@/lib/api/scoped";
import { verifiedMutationOrigin } from "@/lib/operator-origin";

type Context = { params: Promise<{ projectId: string; conversationId: string; planId: string }> };

export async function POST(request: Request, context: Context) {
  if (!verifiedMutationOrigin(request)) return new Response("Accès refusé", { status: 403 });
  const { projectId, conversationId, planId } = await context.params;
  if (![projectId, conversationId, planId].every(isUuid)) return new Response("Plan invalide", { status: 400 });
  let data: unknown;
  try { data = await request.json(); } catch { return new Response("Saisie invalide", { status: 400 }); }
  if (!isRecord(data) || !isUuid(data.task_id)) return new Response("Tâche invalide", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(`projects/${projectId}/conversations/${conversationId}/plans/${planId}/compilations`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task_id: data.task_id }),
    });
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
