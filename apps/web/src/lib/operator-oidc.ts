import "server-only";
import * as oauth from "oauth4webapi";
import { createHmac, timingSafeEqual } from "node:crypto";

export const transactionCookie = "__Host-novalton-oidc-transaction";
export const sessionCookie = "__Host-novalton-operator-session";
export const workspaceCookie = "__Host-novalton-operator-workspace";

type Transaction = { state: string; nonce: string; verifier: string; created: number };

export function configuration() {
  const issuer = process.env.NOVALTON_OPERATOR_OIDC_ISSUER;
  const clientId = process.env.NOVALTON_OPERATOR_OIDC_CLIENT_ID;
  const origin = process.env.NOVALTON_WEB_ORIGIN;
  const secret = process.env.NOVALTON_OPERATOR_OIDC_TRANSACTION_SECRET;
  if (!issuer || !clientId || !origin || !secret || Buffer.byteLength(secret) < 32) throw new Error("OIDC unavailable");
  if (process.env.NOVALTON_OPERATOR_OIDC_AUDIENCE !== clientId) throw new Error("OIDC audience unavailable");
  const issuerUrl = new URL(issuer);
  const originUrl = new URL(origin);
  if (issuerUrl.protocol !== "https:" || originUrl.protocol !== "https:" ||
      issuerUrl.username || issuerUrl.password || issuerUrl.search || issuerUrl.hash ||
      originUrl.origin !== origin || issuerUrl.toString() !== issuer ||
      !/^[\w.:/-]{1,256}$/.test(clientId)) throw new Error("OIDC unavailable");
  return { issuer: issuerUrl, client: { client_id: clientId } satisfies oauth.Client,
    redirectUri: `${origin}/api/operator/auth/callback`, secret };
}

export async function discover(issuer: URL): Promise<oauth.AuthorizationServer> {
  const response = await oauth.discoveryRequest(issuer, { algorithm: "oidc", signal: AbortSignal.timeout(5000) });
  const as = await oauth.processDiscoveryResponse(issuer, response);
  for (const endpoint of [as.authorization_endpoint, as.token_endpoint, as.jwks_uri]) {
    if (!endpoint || new URL(endpoint).protocol !== "https:") throw new Error("OIDC metadata unavailable");
  }
  if (!as.code_challenge_methods_supported?.includes("S256")) throw new Error("OIDC PKCE unavailable");
  return as;
}

export function newTransaction(): Transaction {
  return { state: oauth.generateRandomState(), nonce: oauth.generateRandomNonce(),
    verifier: oauth.generateRandomCodeVerifier(), created: Date.now() };
}

export function sealTransaction(transaction: Transaction, secret: string): string {
  const data = Buffer.from(JSON.stringify(transaction)).toString("base64url");
  const signature = createHmac("sha256", secret).update(data).digest("base64url");
  return `${data}.${signature}`;
}

export function openTransaction(value: string | undefined, secret: string): Transaction | null {
  if (!value || value.length > 2048) return null;
  const parts = value.split(".");
  if (parts.length !== 2 || !parts.every((part) => /^[\w-]+$/.test(part))) return null;
  const expected = createHmac("sha256", secret).update(parts[0]).digest();
  const received = Buffer.from(parts[1], "base64url");
  if (expected.length !== received.length || !timingSafeEqual(expected, received)) return null;
  try {
    const tx = JSON.parse(Buffer.from(parts[0], "base64url").toString()) as Transaction;
    if (!Number.isSafeInteger(tx.created) || tx.created > Date.now() ||
        Date.now() - tx.created > 300_000 ||
        ![tx.state, tx.nonce, tx.verifier].every((s) => typeof s === "string" && /^[\w-]{32,128}$/.test(s))) return null;
    return tx;
  } catch { return null; }
}

/** Only a callback for our live login transaction may replace an existing human session. */
export function matchesOidcCallback(tx: Transaction | null, callback: URL, origin: string): boolean {
  const states = callback.searchParams.getAll("state");
  return tx !== null && callback.origin === origin && states.length === 1 && states[0] === tx.state;
}

export const cookieOptions = { secure: true, httpOnly: true, sameSite: "lax" as const,
  path: "/" };

type ExpirableCookieSink = {
  set(name: string, value: string, options: typeof cookieOptions & { maxAge: number }): unknown;
};

/** Remove credentials left by a prior operator when sign-in fails or the user signs out. */
export function clearOperatorSessionCookies(cookies: ExpirableCookieSink): void {
  for (const name of [transactionCookie, sessionCookie, workspaceCookie]) {
    cookies.set(name, "", { ...cookieOptions, maxAge: 0 });
  }
}

export async function exchangeCode(as: oauth.AuthorizationServer, client: oauth.Client,
  redirectUri: string, tx: Transaction, callback: URL,
  clientSecret?: string): Promise<{ token: string; maxAge: number }> {
  const params = oauth.validateAuthResponse(as, client, callback, tx.state);
  const response = await oauth.authorizationCodeGrantRequest(as, client,
    clientSecret ? oauth.ClientSecretPost(clientSecret) : oauth.None(), params,
    redirectUri, tx.verifier, { signal: AbortSignal.timeout(7000) });
  const result = await oauth.processAuthorizationCodeResponse(as, client, response,
    { expectedNonce: tx.nonce, requireIdToken: true, maxAge: 3600 });
  await oauth.validateApplicationLevelSignature(as, response, { signal: AbortSignal.timeout(5000) });
  const claims = oauth.getValidatedIdTokenClaims(result);
  const token = result.id_token;
  const now = Math.floor(Date.now() / 1000);
  if (!claims || !token || token.length > 8192 ||
      JSON.parse(Buffer.from(token.split(".")[0], "base64url").toString()).alg !== "RS256" ||
      typeof claims.sub !== "string" || !claims.sub ||
      typeof claims.auth_time !== "number" || !Number.isInteger(claims.auth_time) ||
      typeof claims.iat !== "number" || typeof claims.exp !== "number" ||
      claims.auth_time > claims.iat || claims.iat - claims.auth_time > 3600 ||
      claims.exp <= now || claims.exp - claims.iat > 3600) throw new Error("OIDC identity unavailable");
  return { token, maxAge: Math.min(claims.exp - now, 3600) };
}
