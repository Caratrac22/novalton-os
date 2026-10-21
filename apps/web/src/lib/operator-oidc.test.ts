import assert from "node:assert/strict";
import { generateKeyPairSync, sign } from "node:crypto";
import { test } from "node:test";
import { configuration, discover, exchangeCode, newTransaction, openTransaction, sealTransaction } from "./operator-oidc.ts";

test("login requires an exact HTTPS issuer, web origin, and server transaction secret", () => {
  const before = { ...process.env };
  try {
    process.env.NOVALTON_OPERATOR_OIDC_ISSUER = "https://id.example.test/";
    process.env.NOVALTON_OPERATOR_OIDC_CLIENT_ID = "operator";
    process.env.NOVALTON_OPERATOR_OIDC_AUDIENCE = "operator";
    process.env.NOVALTON_WEB_ORIGIN = "https://web.example.test";
    process.env.NOVALTON_OPERATOR_OIDC_TRANSACTION_SECRET = "s".repeat(32);
    assert.equal(configuration().redirectUri, "https://web.example.test/api/operator/auth/callback");
    process.env.NOVALTON_WEB_ORIGIN = "http://web.example.test";
    assert.throws(configuration);
    process.env.NOVALTON_WEB_ORIGIN = "https://web.example.test";
    process.env.NOVALTON_OPERATOR_OIDC_ISSUER = "http://id.example.test/";
    assert.throws(configuration);
    process.env.NOVALTON_OPERATOR_OIDC_ISSUER = "https://id.example.test/";
    process.env.NOVALTON_OPERATOR_OIDC_TRANSACTION_SECRET = "short";
    assert.throws(configuration);
  } finally { process.env = before; }
});

test("login transaction rejects tampering, expiration, future timestamps and substitution", () => {
  const secret = "secret".repeat(8);
  const tx = newTransaction();
  const sealed = sealTransaction(tx, secret);
  assert.deepEqual(openTransaction(sealed, secret), tx);
  assert.equal(openTransaction(sealed, "other".repeat(8)), null);
  assert.equal(openTransaction(`${sealed}x`, secret), null);
  assert.equal(openTransaction(sealTransaction({ ...tx, created: Date.now() - 301_000 }, secret), secret), null);
  assert.equal(openTransaction(sealTransaction({ ...tx, created: Date.now() + 1_000 }, secret), secret), null);
});

test("OIDC code exchange validates state, nonce, human authentication, signature and PKCE", async () => {
  const previous = globalThis.fetch;
  const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const jwk = publicKey.export({ format: "jwk" });
  const issuer = new URL("https://id.example.test/");
  const client = { client_id: "operator" };
  const redirectUri = "https://web.example.test/api/operator/auth/callback";
  const tx = newTransaction();
  let nonce = tx.nonce;
  let signatureValid = true;
  let tokenRequests = 0;
  const now = Math.floor(Date.now() / 1000);
  try {
    globalThis.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      if (url.pathname === "/.well-known/openid-configuration") return Response.json({
        issuer: issuer.href, authorization_endpoint: `${issuer}authorize`,
        token_endpoint: `${issuer}token`, jwks_uri: `${issuer}jwks`,
        code_challenge_methods_supported: ["S256"], id_token_signing_alg_values_supported: ["RS256"],
      });
      if (url.pathname === "/jwks") return Response.json({ keys: [{ ...jwk, kid: "current", use: "sig", alg: "RS256" }] });
      if (url.pathname === "/token") {
        tokenRequests++;
        const body = new URLSearchParams(init?.body as string);
        assert.equal(body.get("code_verifier"), tx.verifier);
        assert.equal(body.get("redirect_uri"), redirectUri);
        const header = Buffer.from(JSON.stringify({ typ: "JWT", alg: "RS256", kid: "current" })).toString("base64url");
        const claims = Buffer.from(JSON.stringify({ iss: issuer.href, aud: client.client_id,
          sub: "human-123", nonce, iat: now, exp: now + 600, auth_time: now - 30 })).toString("base64url");
        const message = `${header}.${claims}`;
        const signature = sign("RSA-SHA256", Buffer.from(message), privateKey).toString("base64url");
        return Response.json({ access_token: "opaque", token_type: "Bearer", id_token:
          `${message}.${signatureValid ? signature : "invalid"}` });
      }
      throw new Error(`Unexpected issuer request: ${url.pathname}`);
    };
    const as = await discover(issuer);
    await assert.rejects(exchangeCode(as, client, redirectUri, tx,
      new URL(`${redirectUri}?code=one&state=forged`)));
    assert.equal(tokenRequests, 0);
    nonce = "substituted";
    await assert.rejects(exchangeCode(as, client, redirectUri, tx,
      new URL(`${redirectUri}?code=two&state=${tx.state}`)));
    nonce = tx.nonce;
    signatureValid = false;
    await assert.rejects(exchangeCode(as, client, redirectUri, tx,
      new URL(`${redirectUri}?code=three&state=${tx.state}`)));
    signatureValid = true;
    const result = await exchangeCode(as, client, redirectUri, tx,
      new URL(`${redirectUri}?code=four&state=${tx.state}`));
    assert.ok(result.token.split(".").length === 3);
    assert.ok(result.maxAge > 0 && result.maxAge <= 600);
    assert.equal(tokenRequests, 3);
  } finally { globalThis.fetch = previous; }
});
