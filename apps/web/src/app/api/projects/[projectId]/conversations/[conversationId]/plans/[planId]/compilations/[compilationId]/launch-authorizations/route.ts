import { scopedSessionFetch, isRecord, isUuid } from "@/lib/api/scoped";
import { verifiedMutationOrigin } from "@/lib/operator-origin";

type Params = { projectId: string; conversationId: string; planId: string; compilationId: string };
type Context = { params: Promise<Params> };

function path({ projectId, conversationId, planId, compilationId }: Params): string | null {
  if (![projectId, conversationId, planId, compilationId].every(isUuid)) return null;
  return `projects/${projectId}/conversations/${conversationId}/plans/${planId}/compilations/${compilationId}/launch-authorizations`;
}

export async function GET(_request: Request, { params }: Context) {
  const destination = path(await params);
  if (!destination) return new Response("Proposition invalide", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(destination);
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}

export async function POST(request: Request, { params }: Context) {
  if (!verifiedMutationOrigin(request)) return new Response("Accès refusé", { status: 403 });
  const destination = path(await params);
  if (!destination) return new Response("Proposition invalide", { status: 400 });
  let data: unknown;
  try { data = await request.json(); } catch { return new Response("Saisie invalide", { status: 400 }); }
  if (!isRecord(data) || data.confirmation !== "AUTHORIZE_DISPOSABLE_TEST_LAUNCH" ||
    data.environment !== "DISPOSABLE_TEST" || data.provider_id !== "local" ||
    !isUuid(data.request_id) || typeof data.model_id !== "string" || data.model_id.length < 1 || data.model_id.length > 256 ||
    !Number.isInteger(data.max_model_calls) || !Number.isInteger(data.max_duration_seconds) ||
    typeof data.current_password !== "string" || data.current_password.length < 1) {
    return new Response("Autorisation invalide", { status: 400 });
  }
  try {
    const upstream = await scopedSessionFetch(destination, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
    });
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
