import { NextResponse } from "next/server";
import { verifiedMutationOrigin } from "@/lib/operator-origin";
import { clearOperatorSessionCookies } from "@/lib/operator-oidc";

export async function POST(request: Request) {
  if (!verifiedMutationOrigin(request)) return new Response("Forbidden", { status: 403 });
  const result = NextResponse.redirect(new URL("/operator", process.env.NOVALTON_WEB_ORIGIN), 303);
  clearOperatorSessionCookies(result.cookies);
  result.headers.set("Cache-Control", "no-store");
  return result;
}
