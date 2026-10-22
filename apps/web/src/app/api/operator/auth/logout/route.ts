import { NextResponse } from "next/server";
import { verifiedMutationOrigin } from "@/lib/operator-origin";
import { cookieOptions, sessionCookie, transactionCookie } from "@/lib/operator-oidc";
import { cookies } from "next/headers";
import { getApiBaseUrl } from "@/lib/api/config";

export async function POST(request: Request) {
  if (!verifiedMutationOrigin(request)) return new Response("Forbidden", { status: 403 });
  const token = (await cookies()).get(sessionCookie)?.value;
  if (token?.startsWith("nvl_")) {
    try {
      const revoked = await fetch(`${getApiBaseUrl()}/api/v1/local-auth/logout`, {
        method: "POST", headers: { Authorization: `Bearer ${token}` },
        cache: "no-store", signal: AbortSignal.timeout(7000),
      });
      if (revoked.status !== 204 && revoked.status !== 401) throw new Error("Revoke unavailable");
    } catch { return new Response("Révocation temporairement indisponible.", { status: 503 }); }
  }
  const result = NextResponse.redirect(new URL("/operator", process.env.NOVALTON_WEB_ORIGIN), 303);
  result.cookies.set(sessionCookie, "", { ...cookieOptions, maxAge: 0 });
  result.cookies.set(transactionCookie, "", { ...cookieOptions, maxAge: 0 });
  result.cookies.set("__Host-novalton-operator-workspace", "", { ...cookieOptions, maxAge: 0 });
  result.headers.set("Cache-Control", "no-store");
  return result;
}
