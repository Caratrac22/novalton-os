import { scopedSessionFetch, isUuid, isRecord } from "@/lib/api/scoped";
import { verifiedMutationOrigin } from "@/lib/operator-origin";

type Context = { params: Promise<{ projectId: string }> };
export async function GET(request: Request, { params }: Context) {
  const { projectId } = await params;
  if (!isUuid(projectId)) return new Response("Projet invalide", { status: 400 });
  try {
    const offset = new URL(request.url).searchParams.get("offset") ?? "0";
    if (!/^(0|[1-9]\d{0,5})$/.test(offset)) return new Response("Page invalide", { status: 400 });
    const upstream = await scopedSessionFetch(`projects/${projectId}/conversations?limit=50&offset=${offset}`);
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
export async function POST(request: Request, { params }: Context) {
  if (!verifiedMutationOrigin(request)) return new Response("Accès refusé", { status: 403 });
  const { projectId } = await params;
  if (!isUuid(projectId)) return new Response("Projet invalide", { status: 400 });
  let body: unknown;
  try { body = await request.json(); } catch { return new Response("Saisie invalide", { status: 400 }); }
  if (!isRecord(body) || typeof body.title !== "string" || !body.title.trim() || body.title.length > 200) return new Response("Titre invalide", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(`projects/${projectId}/conversations`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: body.title }), signal: AbortSignal.timeout(7000) });
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
