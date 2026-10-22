// Isolated OIDC protocol smoke: real Next routes, local HTTPS issuer, test API.
import assert from "node:assert/strict";
import { createHash, generateKeyPairSync, sign, verify } from "node:crypto";
import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer as createHttpServer, request as httpRequest } from "node:http";
import { createServer as createHttpsServer, request as httpsRequest } from "node:https";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer as createNetServer } from "node:net";

const temp = mkdtempSync(join(tmpdir(), "novalton-oidc-smoke-"));
const keyPath = join(temp, "key.pem");
const certPath = join(temp, "cert.pem");
execFileSync("openssl", ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
  "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
  "-keyout", keyPath, "-out", certPath], { stdio: "ignore" });
const tls = { key: readFileSync(keyPath), cert: readFileSync(certPath) };
const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: "jwk" }), kid: "local-test", use: "sig", alg: "RS256" };
const servers = [];
let next;
let revoked = false;
let codes = new Map();
const scope = { tenant: "89cfc055-366e-5bcb-b65f-4f367185bf6d",
  workspace: "b640b64f-8e55-53e8-a5b2-3beff9d5af82" };
const dispatchId = "e850ad05-55dd-4f30-88af-ff91e9dc5263";
const workflowId = "a65a79e8-fae9-4edd-9d05-ace6674a724d";
const taskId = "02bdb65f-4ac1-4d0e-bf34-614f5f7e7c77";
let cancelled = false;

async function port() {
  const server = createNetServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const value = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return value;
}
async function listen(server) {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  servers.push(server);
  return server.address().port;
}
function jwt(claims) {
  const head = Buffer.from(JSON.stringify({ alg: "RS256", typ: "JWT", kid: jwk.kid })).toString("base64url");
  const body = Buffer.from(JSON.stringify(claims)).toString("base64url");
  const input = `${head}.${body}`;
  return `${input}.${sign("RSA-SHA256", Buffer.from(input), privateKey).toString("base64url")}`;
}
function validToken(token, issuer) {
  try {
    const [head, body, signature] = token.split(".");
    const claims = JSON.parse(Buffer.from(body, "base64url"));
    return verify("RSA-SHA256", Buffer.from(`${head}.${body}`), publicKey,
      Buffer.from(signature, "base64url")) && claims.iss === issuer &&
      claims.aud === "operator-test" && claims.sub === "human-123" &&
      claims.exp > Date.now() / 1000;
  } catch { return false; }
}
function respond(res, status, body = "", headers = {}) {
  res.writeHead(status, headers); res.end(body);
}
function httpsCall(url, { cookie, method = "GET", origin, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = httpsRequest(url, { ca: tls.cert, method, headers: {
      ...(cookie ? { Cookie: cookie } : {}), ...(origin ? { Origin: origin } : {}),
      ...(body ? { "Content-Type": "application/x-www-form-urlencoded" } : {}),
    } }, (res) => {
      const chunks = [];
      res.on("data", (part) => chunks.push(part));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers,
        body: Buffer.concat(chunks).toString() }));
    });
    req.on("error", reject); req.end(body);
  });
}
function cookie(response, name) {
  const line = response.headers["set-cookie"]?.find((item) => item.startsWith(`${name}=`));
  assert.ok(line, `missing ${name} cookie`);
  assert.match(line, /Secure/); assert.match(line, /HttpOnly/); assert.match(line, /SameSite=lax/i);
  return line.split(";")[0];
}

try {
  const issuerPort = await port();
  const issuer = `https://localhost:${issuerPort}/`;
  const issuerServer = createHttpsServer(tls, async (req, res) => {
    const url = new URL(req.url, issuer);
    if (url.pathname === "/.well-known/openid-configuration") return respond(res, 200,
      JSON.stringify({ issuer, authorization_endpoint: `${issuer}authorize`,
        token_endpoint: `${issuer}token`, jwks_uri: `${issuer}jwks`,
        code_challenge_methods_supported: ["S256"], id_token_signing_alg_values_supported: ["RS256"] }),
      { "Content-Type": "application/json" });
    if (url.pathname === "/jwks") return respond(res, 200, JSON.stringify({ keys: [jwk] }),
      { "Content-Type": "application/json" });
    if (url.pathname === "/authorize") {
      assert.equal(url.searchParams.get("code_challenge_method"), "S256");
      const code = `code-${codes.size}`;
      codes.set(code, { nonce: url.searchParams.get("nonce"), challenge: url.searchParams.get("code_challenge") });
      const redirect = new URL(url.searchParams.get("redirect_uri"));
      redirect.searchParams.set("code", code);
      redirect.searchParams.set("state", url.searchParams.get("state"));
      return respond(res, 302, "", { Location: redirect.href });
    }
    if (url.pathname === "/token") {
      const parts = [];
      for await (const part of req) parts.push(part);
      const form = new URLSearchParams(Buffer.concat(parts).toString());
      const code = codes.get(form.get("code"));
      if (!code || createHash("sha256").update(form.get("code_verifier") ?? "")
        .digest("base64url") !== code.challenge) return respond(res, 400);
      codes.delete(form.get("code"));
      const now = Math.floor(Date.now() / 1000);
      return respond(res, 200, JSON.stringify({ access_token: "local-only", token_type: "Bearer",
        id_token: jwt({ iss: issuer, aud: "operator-test", sub: "human-123", nonce: code.nonce,
          iat: now, exp: now + 600, auth_time: now - 10 }) }),
      { "Content-Type": "application/json" });
    }
    respond(res, 404);
  });
  await new Promise((resolve) => issuerServer.listen(issuerPort, "127.0.0.1", resolve));
  servers.push(issuerServer);

  const apiPort = await listen(createHttpServer((req, res) => {
    const token = req.headers.authorization?.replace(/^Bearer /, "");
    if (revoked || !validToken(token, issuer)) return respond(res, 401);
    const base = `/api/v1/tenants/${scope.tenant}/workspaces/${scope.workspace}/dispatch/requests`;
    const json = (value) => respond(res, 200, JSON.stringify(value), { "Content-Type": "application/json" });
    if (req.url === `${base}?limit=1` || req.url === `${base}?limit=100`)
      return json([{ id: dispatchId, workflow_run_id: workflowId, task_id: taskId,
        status: cancelled ? "CANCELLED" : "BLOCKED", generation: 3, priority: 1,
        attempt_count: 3, model_call_count: 3, reserved_estimated_exposure: "0.001",
        stop_reason: "worker_lost_heartbeat" }]);
    if (req.url === `${base}/${dispatchId}/workflow`) return json({
      workflow_plan: { title: "Isolated integration workflow" },
      workflow_run: { status: "COMPLETED" },
      step_details: ["Manager", "Developer", "QA"].map((role) => ({
        specialization_role: role, agent_run: { status: "COMPLETED", model_runs: [{
          id: dispatchId, provider_model_id: "mock/model", status: "SUCCEEDED" }] },
      })),
    });
    if (req.url === `${base}/${dispatchId}/cost-evidence`) return json([{
      model_run_id: dispatchId, classification: "OBSERVED_ESTIMATE",
      catalog_priced_usage: "0.0002", reserved_estimated_exposure: "0.001",
      provider_reported_cost: null, provider_report_exceeds_reservation: false,
      provider_billing_status: "BILLING_UNVERIFIED",
    }]);
    if (req.url === `${base}/${dispatchId}/attempts`) return json([{ generation: 3,
      outcome: "BLOCKED", reason_code: "worker_lost_heartbeat" }]);
    if (req.url === `${base}/${dispatchId}/cancel` && req.method === "POST") {
      cancelled = true;
      return json({ id: dispatchId, status: "CANCELLED" });
    }
    respond(res, 404);
  }));
  const nextPort = await port();
  const proxyPort = await port();
  const webOrigin = `https://localhost:${proxyPort}`;
  const proxy = createHttpsServer(tls, (req, res) => {
    const upstream = httpRequest({ hostname: "127.0.0.1", port: nextPort, path: req.url,
      method: req.method, headers: { ...req.headers, host: `localhost:${proxyPort}`,
        "x-forwarded-proto": "https", "x-forwarded-host": `localhost:${proxyPort}` } }, (response) => {
      res.writeHead(response.statusCode, response.headers); response.pipe(res);
    });
    upstream.on("error", () => respond(res, 502)); req.pipe(upstream);
  });
  await new Promise((resolve) => proxy.listen(proxyPort, "127.0.0.1", resolve));
  servers.push(proxy);
  next = spawn(process.execPath, ["../../node_modules/next/dist/bin/next", "start", "-p",
    String(nextPort), "-H", "127.0.0.1"], { cwd: new URL("..", import.meta.url).pathname,
    env: { ...process.env, NODE_EXTRA_CA_CERTS: certPath, NOVALTON_WEB_ORIGIN: webOrigin,
      NOVALTON_OPERATOR_OIDC_ISSUER: issuer, NOVALTON_OPERATOR_OIDC_CLIENT_ID: "operator-test",
      NOVALTON_OPERATOR_OIDC_AUDIENCE: "operator-test",
      NOVALTON_OPERATOR_OIDC_TRANSACTION_SECRET: "isolated-transaction-secret-32-bytes",
      NOVALTON_API_BASE_URL: `http://127.0.0.1:${apiPort}`,
      NOVALTON_TENANT_ID: scope.tenant, NOVALTON_WORKSPACE_ID: scope.workspace },
    stdio: "ignore" });
  let ready = false;
  for (let i = 0; i < 100; i++) {
    await new Promise((resolve) => setTimeout(resolve, 100));
    try { if ((await httpsCall(`${webOrigin}/operator`)).status === 200) { ready = true; break; } }
    catch { /* bounded startup retry */ }
  }
  assert.ok(ready, "Next did not start");
  const started = await httpsCall(`${webOrigin}/api/operator/auth/start`);
  assert.equal(started.status, 307);
  const txCookie = cookie(started, "__Host-novalton-oidc-transaction");
  const authorization = await httpsCall(started.headers.location);
  assert.equal(authorization.status, 302);
  const forged = new URL(authorization.headers.location);
  forged.searchParams.set("state", "forged");
  const rejected = await httpsCall(forged.href, { cookie: txCookie });
  assert.match(rejected.headers.location, /auth=failed/);
  assert.equal(rejected.headers["set-cookie"].some((item) => item.startsWith("__Host-novalton-operator-session=")), false);
  const callback = await httpsCall(authorization.headers.location, { cookie: txCookie });
  assert.equal(callback.status, 307);
  assert.equal(callback.headers.location, `${webOrigin}/operator`);
  const session = cookie(callback, "__Host-novalton-operator-session");
  const replay = await httpsCall(authorization.headers.location, { cookie: txCookie });
  assert.match(replay.headers.location, /auth=failed/);
  const consoleResponse = await httpsCall(`${webOrigin}/operator`, { cookie: session });
  assert.equal(consoleResponse.status, 200);
  assert.match(consoleResponse.body, new RegExp(workflowId));
  const details = await httpsCall(`${webOrigin}/operator/${dispatchId}`, { cookie: session });
  assert.equal(details.status, 200);
  for (const role of ["Manager", "Developer", "QA"])
    assert.match(details.body, new RegExp(role));
  assert.match(details.body, /BILLING_UNVERIFIED/);
  assert.equal((await httpsCall(`${webOrigin}/api/operator/workspace`, {
    method: "POST", cookie: session, origin: "https://forged.example.test",
    body: `workspace_id=${scope.workspace}`,
  })).status, 403);
  assert.equal((await httpsCall(`${webOrigin}/api/operator/workspace`, {
    method: "POST", cookie: session, origin: webOrigin,
    body: `workspace_id=${scope.workspace}`,
  })).status, 303);
  const wrongOrigin = await httpsCall(`${webOrigin}/api/operator/${dispatchId}/cancel`, {
    method: "POST", cookie: session, origin: "https://forged.example.test",
    body: "{}",
  });
  assert.equal(wrongOrigin.status, 403);
  assert.equal(cancelled, false);
  const decision = await httpsCall(`${webOrigin}/api/operator/${dispatchId}/cancel`, {
    method: "POST", cookie: session, origin: webOrigin,
    body: "{}",
  });
  assert.equal(decision.status, 200);
  assert.equal(cancelled, true);
  revoked = true;
  const revokedResponse = await httpsCall(`${webOrigin}/operator`, { cookie: session });
  assert.match(revokedResponse.body, /permission revoked/);
  assert.equal((await httpsCall(`${webOrigin}/api/operator/auth/logout`, {
    method: "POST", cookie: session, origin: "https://forged.example.test",
  })).status, 403);
  const logout = await httpsCall(`${webOrigin}/api/operator/auth/logout`, {
    method: "POST", cookie: session, origin: webOrigin,
  });
  assert.equal(logout.status, 303);
  assert.match(logout.headers["set-cookie"].find((item) => item.startsWith("__Host-novalton-operator-session=")), /Max-Age=0/i);
  console.log(JSON.stringify({ oidc: "local HTTPS issuer", next: "real server routes",
    backend: "signed-token validating test stub", revoked: true }));
} finally {
  if (next) { next.kill("SIGTERM"); await new Promise((resolve) => {
    if (next.exitCode !== null) return resolve();
    next.once("exit", resolve); setTimeout(() => { next.kill("SIGKILL"); resolve(); }, 3000);
  }); }
  await Promise.all(servers.map((server) => new Promise((resolve) => server.close(resolve))));
  rmSync(temp, { recursive: true, force: true });
}
