import * as oauth from "oauth4webapi";
import { NextResponse } from "next/server";
import { configuration, cookieOptions, discover, newTransaction, sealTransaction, transactionCookie } from "@/lib/operator-oidc";

export async function GET() {
  try {
    const { issuer, client, redirectUri, secret } = configuration();
    const as = await discover(issuer);
    const tx = newTransaction();
    const destination = new URL(as.authorization_endpoint!);
    destination.searchParams.set("client_id", client.client_id);
    destination.searchParams.set("redirect_uri", redirectUri);
    destination.searchParams.set("response_type", "code");
    destination.searchParams.set("scope", "openid");
    destination.searchParams.set("state", tx.state);
    destination.searchParams.set("nonce", tx.nonce);
    destination.searchParams.set("code_challenge_method", "S256");
    destination.searchParams.set("code_challenge", await oauth.calculatePKCECodeChallenge(tx.verifier));
    destination.searchParams.set("max_age", "3600");
    const result = NextResponse.redirect(destination);
    result.cookies.set(transactionCookie, sealTransaction(tx, secret), { ...cookieOptions, maxAge: 300 });
    result.headers.set("Cache-Control", "no-store");
    return result;
  } catch { return new Response("Sign-in unavailable", { status: 503 }); }
}
