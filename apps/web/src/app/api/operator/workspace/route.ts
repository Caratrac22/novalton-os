import { NextResponse } from "next/server";
import { dispatchUpstream } from "@/lib/api/dispatch";
import { operatorWorkspaceScopes } from "@/lib/api/config";
import { cookieOptions } from "@/lib/operator-oidc";
import { verifiedMutationOrigin } from "@/lib/operator-origin";

export async function POST(request: Request) {
  if (!verifiedMutationOrigin(request)) return new Response("Forbidden", { status: 403 });
  try {
    const form = await request.formData();
    const candidate = form.get("workspace_id");
    if (typeof candidate !== "string") return new Response("Invalid workspace", { status: 400 });
    const scope = operatorWorkspaceScopes().find((item) => item.workspaceId === candidate);
    if (!scope) return new Response("Invalid workspace", { status: 400 });
    const checked = await dispatchUpstream("requests?limit=1", undefined, scope);
    if (!checked?.ok) return new Response("Workspace permission unavailable", { status: 403 });
    const response = NextResponse.redirect(new URL("/operator", process.env.NOVALTON_WEB_ORIGIN), 303);
    response.cookies.set("__Host-novalton-operator-workspace", candidate,
      { ...cookieOptions, maxAge: 3600 });
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch { return new Response("Workspace unavailable", { status: 503 }); }
}
