import { NextRequest, NextResponse } from "next/server";
import { clearOperatorSessionCookies, configuration, cookieOptions, discover, exchangeCode, matchesOidcCallback, openTransaction, sessionCookie, transactionCookie, workspaceCookie } from "@/lib/operator-oidc";

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
    const callback = new URL(request.url);
    if (!matchesOidcCallback(tx, callback, origin)) return failure;
    // Only a genuine ongoing login may replace the previously signed-in human.
    clearOperatorSessionCookies(failure.cookies);
    const as = await discover(issuer);
    const { token, maxAge } = await exchangeCode(as, client, redirectUri, tx!, callback,
      process.env.NOVALTON_OPERATOR_OIDC_CLIENT_SECRET);
    const result = NextResponse.redirect(`${origin}/operator`);
    result.cookies.set(transactionCookie, "", { ...cookieOptions, maxAge: 0 });
    // A different human identity must not inherit a previous workspace selection.
    result.cookies.set(workspaceCookie, "", { ...cookieOptions, maxAge: 0 });
    result.cookies.set(sessionCookie, token, { ...cookieOptions, sameSite: "lax", maxAge });
    result.headers.set("Cache-Control", "no-store");
    return result;
  } catch { return failure; }
}
