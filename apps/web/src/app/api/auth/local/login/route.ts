import { NextResponse } from "next/server";
import { getApiBaseUrl, operatorWorkspaceScopes } from "@/lib/api/config";
import { isRecord } from "@/lib/api/scoped";
import { cookieOptions, sessionCookie } from "@/lib/operator-oidc";
import { verifiedMutationOrigin } from "@/lib/operator-origin";

export async function POST(request: Request) {
  if (!verifiedMutationOrigin(request)) return new Response("Accès refusé", { status: 403 });
  let body: unknown;
  try { body = await request.json(); } catch { return Response.json({ message: "Identifiants invalides." }, { status: 400 }); }
  if (!isRecord(body) || typeof body.login !== "string" || typeof body.password !== "string" ||
      body.login.length > 128 || body.password.length > 128) return Response.json({ message: "Identifiants invalides." }, { status: 400 });
  try {
    const upstream = await fetch(`${getApiBaseUrl()}/api/v1/local-auth/login`, {
      method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ login: body.login, password: body.password }), signal: AbortSignal.timeout(7000),
    });
    if (!upstream.ok) return Response.json({ message: "Identifiants invalides ou connexion temporairement indisponible." }, { status: upstream.status === 401 ? 401 : 503 });
    const result: unknown = await upstream.json();
    if (!isRecord(result) || typeof result.token !== "string" || !/^nvl_[\w-]{43}$/.test(result.token) || !Array.isArray(result.scopes)) throw new Error("Réponse de session invalide");
    const scopes = result.scopes as unknown[];
    const allowed = operatorWorkspaceScopes().find((scope) => scopes.some((entry: unknown) =>
      isRecord(entry) && entry.tenant_id === scope.tenantId && entry.workspace_id === scope.workspaceId));
    if (!allowed) return Response.json({ message: "Aucun espace autorisé n’est configuré dans cette instance." }, { status: 403 });
    const response = NextResponse.json({ ok: true });
    response.cookies.set(sessionCookie, result.token, { ...cookieOptions, maxAge: 3600 });
    response.cookies.set("__Host-novalton-operator-workspace", allowed.workspaceId, { ...cookieOptions, maxAge: 3600 });
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch { return Response.json({ message: "Service de connexion indisponible." }, { status: 503 }); }
}
