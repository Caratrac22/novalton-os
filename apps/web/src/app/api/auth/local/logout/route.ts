import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { getApiBaseUrl } from "@/lib/api/config";
import { cookieOptions, sessionCookie, transactionCookie } from "@/lib/operator-oidc";
import { verifiedMutationOrigin } from "@/lib/operator-origin";

export async function POST(request: Request) {
  if (!verifiedMutationOrigin(request)) return new Response("Accès refusé", { status: 403 });
  const token = (await cookies()).get(sessionCookie)?.value;
  if (token?.startsWith("nvl_")) {
    try {
      const result = await fetch(`${getApiBaseUrl()}/api/v1/local-auth/logout`, {
        method: "POST", headers: { Authorization: `Bearer ${token}` },
        cache: "no-store", signal: AbortSignal.timeout(7000),
      });
      if (result.status !== 204 && result.status !== 401) throw new Error("Révocation indisponible");
    } catch { return new Response("Impossible de révoquer la session. Réessayez.", { status: 503 }); }
  }
  const response = NextResponse.redirect(new URL("/login", process.env.NOVALTON_WEB_ORIGIN), 303);
  response.cookies.set(sessionCookie, "", { ...cookieOptions, maxAge: 0 });
  response.cookies.set(transactionCookie, "", { ...cookieOptions, maxAge: 0 });
  response.cookies.set("__Host-novalton-operator-workspace", "", { ...cookieOptions, maxAge: 0 });
  response.headers.set("Cache-Control", "no-store");
  return response;
}
