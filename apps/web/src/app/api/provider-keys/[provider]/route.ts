import { scopedSessionFetch, isRecord } from "@/lib/api/scoped";
import { verifiedMutationOrigin } from "@/lib/operator-origin";
type Context = { params: Promise<{ provider: string }> };
async function proxy(request: Request, context: Context, method: "PUT" | "PATCH" | "DELETE") {
  if (!verifiedMutationOrigin(request)) return new Response("Accès refusé", { status: 403 });
  const { provider } = await context.params;
  if (provider !== "openrouter" && provider !== "openai_compatible") return new Response("Fournisseur inconnu", { status: 400 });
  let body: unknown;
  try { body = await request.json(); } catch { return new Response("Saisie invalide", { status: 400 }); }
  if (!isRecord(body) || typeof body.current_password !== "string" || !body.current_password || body.current_password.length > 128 ||
      (method === "PUT" && (typeof body.secret !== "string" || body.secret.length < 8 || body.secret.length > 4096)) ||
      (method === "PATCH" && typeof body.enabled !== "boolean")) return new Response("Saisie invalide", { status: 400 });
  try {
    const upstream = await scopedSessionFetch(`provider-keys/${provider}`, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
export const PUT = (request: Request, context: Context) => proxy(request, context, "PUT");
export const PATCH = (request: Request, context: Context) => proxy(request, context, "PATCH");
export const DELETE = (request: Request, context: Context) => proxy(request, context, "DELETE");
