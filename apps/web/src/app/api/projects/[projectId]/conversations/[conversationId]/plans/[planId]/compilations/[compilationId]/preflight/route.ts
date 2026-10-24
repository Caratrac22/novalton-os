import { scopedSessionFetch, isUuid } from "@/lib/api/scoped";

type Context = { params: Promise<{ projectId: string; conversationId: string; planId: string; compilationId: string }> };

export async function GET(_request: Request, context: Context) {
  const { projectId, conversationId, planId, compilationId } = await context.params;
  if (![projectId, conversationId, planId, compilationId].every(isUuid)) return new Response("Proposition invalide", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(`projects/${projectId}/conversations/${conversationId}/plans/${planId}/compilations/${compilationId}/preflight`);
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
