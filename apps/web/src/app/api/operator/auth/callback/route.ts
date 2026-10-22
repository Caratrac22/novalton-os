import { NextRequest, NextResponse } from "next/server";
import { configuration, cookieOptions, discover, exchangeCode, openTransaction, sessionCookie, transactionCookie } from "@/lib/operator-oidc";

export async function GET(request: NextRequest) {
  let origin: string;
  try { origin = new URL(process.env.NOVALTON_WEB_ORIGIN!).origin; }
  catch { return new Response("Sign-in unavailable", { status: 503 }); }
  // Always consume the transaction, including failed callbacks.
  const failure = NextResponse.redirect(`${origin}/operator?auth=failed`);
  failure.cookies.set(transactionCookie, "", { ...cookieOptions, maxAge: 0 });
  failure.headers.set("Cache-Control", "no-store");
  try {
    const { issuer, client, redirectUri, secret } = configuration();
    const tx = openTransaction(request.cookies.get(transactionCookie)?.value, secret);
    // Next may expose its internal port in request.url behind a TLS reverse proxy.
    // Bind the callback to the configured public host and HTTPS scheme instead.
    if (!tx || request.headers.get("host") !== new URL(origin).host ||
        request.headers.get("x-forwarded-proto") !== "https") return failure;
    const as = await discover(issuer);
    const callback = new URL(redirectUri);
    callback.search = new URL(request.url).search;
    const { token, maxAge } = await exchangeCode(as, client, redirectUri, tx, callback,
      process.env.NOVALTON_OPERATOR_OIDC_CLIENT_SECRET);
    const result = NextResponse.redirect(`${origin}/operator`);
    result.cookies.set(transactionCookie, "", { ...cookieOptions, maxAge: 0 });
    result.cookies.set(sessionCookie, token, { ...cookieOptions, sameSite: "lax", maxAge });
    result.headers.set("Cache-Control", "no-store");
    return result;
  } catch { return failure; }
}
