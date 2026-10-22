import { NextResponse } from "next/server";
import { operatorWorkspaceScopes } from "@/lib/api/config";
import { scopedSessionFetch } from "@/lib/api/scoped";
import { cookieOptions } from "@/lib/operator-oidc";
import { verifiedMutationOrigin } from "@/lib/operator-origin";

export async function POST(request: Request) {
  if (!verifiedMutationOrigin(request)) return new Response("Forbidden", { status: 403 });
  try {
    const form = await request.formData();
    const candidate = form.get("workspace_id");
    const scope = typeof candidate === "string"
      ? operatorWorkspaceScopes().find((item) => item.workspaceId === candidate) : undefined;
    if (!scope) return new Response("Espace invalide", { status: 400 });
    const checked = await scopedSessionFetch("projects?limit=1", {}, scope);
    if (!checked.ok) return new Response("Espace inaccessible", { status: checked.status });
    const response = NextResponse.redirect(new URL("/settings", process.env.NOVALTON_WEB_ORIGIN), 303);
    response.cookies.set("__Host-novalton-operator-workspace", candidate as string,
      { ...cookieOptions, maxAge: 3600 });
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch { return new Response("Service indisponible", { status: 503 }); }
}
