import { verifiedMutationOrigin } from "@/lib/operator-origin";
import { scopedSessionFetch } from "@/lib/api/scoped";
import { isRecord } from "@/lib/api/scoped";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  if (!verifiedMutationOrigin(request)) return new Response("Forbidden", { status: 403 });
  let body: unknown;
  try { body = await request.json(); } catch { return Response.json({ message: "Enter a project name and slug." }, { status: 400 }); }
  if (!isRecord(body) || typeof body.name !== "string" || typeof body.slug !== "string" || !(body.description === null || typeof body.description === "string")) return Response.json({ message: "The project request is incomplete." }, { status: 400 });
  try {
    const upstream = await scopedSessionFetch("projects", { method: "POST", cache: "no-store", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ name: body.name, slug: body.slug, description: body.description }), signal: AbortSignal.timeout(5000) });
    if (!upstream.ok) return Response.json({ message: upstream.status === 401 ? "Connexion requise." : upstream.status === 403 ? "Accès refusé pour cet espace." : upstream.status === 409 ? "Ce nom court existe déjà." : "Le projet n’a pas pu être créé." }, { status: upstream.status });
    return Response.json(await upstream.json(), { status: 201 });
  } catch { return Response.json({ message: "The project service is unavailable." }, { status: 503 }); }
}
