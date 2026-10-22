import { verifiedMutationOrigin } from "@/lib/operator-origin";
import { postWorkflow } from "@/lib/api/workflows";
import { isRecord, isUuid } from "@/lib/api/scoped";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  if (!verifiedMutationOrigin(request)) return new Response("Forbidden", { status: 403 });
  let body: unknown;
  try { body = await request.json(); } catch { return Response.json({ message: "Enter an objective and at least one acceptance criterion." }, { status: 400 }); }
  if (!isRecord(body) || !isUuid(body.projectId) || !isUuid(body.taskId) || typeof body.objective !== "string" || !Array.isArray(body.acceptanceCriteria) || body.acceptanceCriteria.length < 1 || body.acceptanceCriteria.some((item) => typeof item !== "string")) return Response.json({ message: "The workflow request is incomplete." }, { status: 400 });
  try {
    const response = await postWorkflow(`projects/${body.projectId}/tasks/${body.taskId}/development-workflows`, { objective: body.objective, acceptance_criteria: body.acceptanceCriteria });
    if (!response.ok) return Response.json({ message: response.status === 401 ? "Connexion requise." : response.status === 403 ? "Accès refusé pour cet espace." : response.status === 404 ? "Tâche inaccessible." : response.status === 409 ? "Les agents gouvernés sont indisponibles." : "Le workflow n’a pas pu être créé." }, { status: response.status });
    return Response.json(await response.json());
  } catch { return Response.json({ message: "The workflow service is unavailable." }, { status: 503 }); }
}
