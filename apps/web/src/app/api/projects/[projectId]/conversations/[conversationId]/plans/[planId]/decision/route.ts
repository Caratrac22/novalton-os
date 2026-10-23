import { scopedSessionFetch, isUuid, isRecord } from "@/lib/api/scoped";
import { verifiedMutationOrigin } from "@/lib/operator-origin";
export async function POST(request: Request, { params }: { params: Promise<{ projectId: string; conversationId: string; planId: string }> }) {
  if (!verifiedMutationOrigin(request)) return new Response("Accès refusé", { status: 403 });
  const { projectId, conversationId, planId } = await params;
  if (![projectId, conversationId, planId].every(isUuid)) return new Response("Plan invalide", { status: 400 });
  let data: unknown;
  try { data = await request.json(); } catch { return new Response("Saisie invalide", { status: 400 }); }
  if (!isRecord(data) || !["READY_FOR_REVIEW", "APPROVED", "REJECTED", "NEEDS_CHANGES"].includes(String(data.decision))) return new Response("Décision invalide", { status: 400 });
  try { const upstream = await scopedSessionFetch(`projects/${projectId}/conversations/${conversationId}/plans/${planId}/decision`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }); return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } }); }
  catch { return new Response("Service indisponible", { status: 503 }); }
}
