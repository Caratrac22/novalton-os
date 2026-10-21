import { NextResponse } from "next/server";
import { verifiedMutationOrigin } from "@/lib/operator-origin";
import { cookieOptions, sessionCookie, transactionCookie } from "@/lib/operator-oidc";

export async function POST(request: Request) {
  if (!verifiedMutationOrigin(request)) return new Response("Forbidden", { status: 403 });
  const result = NextResponse.redirect(new URL("/operator", process.env.NOVALTON_WEB_ORIGIN), 303);
  result.cookies.set(sessionCookie, "", { ...cookieOptions, maxAge: 0 });
  result.cookies.set(transactionCookie, "", { ...cookieOptions, maxAge: 0 });
  result.cookies.set("__Host-novalton-operator-workspace", "", { ...cookieOptions, maxAge: 0 });
  result.headers.set("Cache-Control", "no-store");
  return result;
}
