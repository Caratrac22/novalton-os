import { scopedSessionFetch, isUuid } from "@/lib/api/scoped";
export async function GET(_request: Request, { params }: { params: Promise<{ projectId: string; conversationId: string; version: string }> }) {
  const { projectId, conversationId, version } = await params;
  if (!isUuid(projectId) || !isUuid(conversationId) || !/^[1-9]\d{0,5}$/.test(version)) return new Response("Version invalide", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(`projects/${projectId}/conversations/${conversationId}/specifications/${version}`);
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
