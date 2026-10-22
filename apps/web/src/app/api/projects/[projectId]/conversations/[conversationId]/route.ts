import { scopedSessionFetch, isUuid } from "@/lib/api/scoped";
export async function GET(_request: Request, { params }: { params: Promise<{ projectId: string; conversationId: string }> }) {
  const { projectId, conversationId } = await params;
  if (!isUuid(projectId) || !isUuid(conversationId)) return new Response("Conversation invalide", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(`projects/${projectId}/conversations/${conversationId}`);
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
