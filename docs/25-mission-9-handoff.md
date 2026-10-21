# Mission 9 handoff

Branch `feature/mission9-oidc-console` is stacked on Mission 8 PR #97 at
`491f2a51805f579a1351ae2602ca9484b4e55c94`. Do not merge the stacked
chain without authorization. Check the final PR head and CI artifact before
restoring this branch in the next session.

## Implemented

- Next.js server routes initiate an OIDC authorization-code login with S256
  PKCE, signed five-minute transaction cookie, state and nonce. The callback
  exchanges the code using `oauth4webapi`, validates issuer/audience, signature
  with issuer JWKS, human `auth_time`, freshness and token lifetime, and sets a
  Secure, HttpOnly, SameSite `__Host-` cookie. Failed callbacks consume the
  transaction. Origin-checked sign-out clears session and workspace cookies.
  No browser-supplied user, role or tenant is trusted. The API still binds the
  issuer and subject to a durable human and rechecks membership and exact grant
  for every request. An optional same-origin HTTPS JWKS URI permits bounded
  rotation instead of the original pinned PEM; exactly one key source is
  configured. The public key cache expires in 60 seconds; unknown keys refresh
  at most once in five seconds.
- A server-configured, at-most-ten-workspace allowlist gives the `/operator`
  console an explicit selector. Selecting a scope requires an Origin-checked
  POST and a successful authenticated backend read of that exact scope. Every
  subsequent read/action remains authorized by the backend. The existing
  Manager/Developer/QA, ModelRun, attempt, approval and explicit resolution
  views remain in use; no authority moved into the browser.
- OpenRouter's completion `id` is stored separately from its request header
  ID on the exact ModelRun. A new trusted internal reconciler fetches its
  `/api/v1/generation?id=...` metadata using a server-held provider credential,
  bounds the response, checks the generation ID, and records one provider
  reported USD `total_cost` per run under a row lock. A unique provider and
  generation key prevents attachment to another run. Identical concurrent
  observations are idempotent; a different amount raises a conflict and
  preserves the first observation. Failures leave cost unknown. The operator
  view distinguishes catalog-priced usage, reserved estimate and provider
  reported cost. `provider_billing_verified` remains false: this is a provider
  usage endpoint, not an independently verified invoice.
- Migration `20261021_0039` adds the generation identity and observation table,
  and guards downgrades containing evidence. The audit updated `certifi` and
  `urllib3` in the API lockfile to patched versions.

## Configuration and safety

Web: set exact `NOVALTON_WEB_ORIGIN` (HTTPS),
`NOVALTON_OPERATOR_OIDC_ISSUER` (HTTPS with exact trailing-path spelling),
`NOVALTON_OPERATOR_OIDC_CLIENT_ID`, matching
`NOVALTON_OPERATOR_OIDC_AUDIENCE`, and a high-entropy
`NOVALTON_OPERATOR_OIDC_TRANSACTION_SECRET` of at least 32 bytes. An optional
`NOVALTON_OPERATOR_OIDC_CLIENT_SECRET` uses client-secret POST; otherwise the
client is public with PKCE. Configure the exact redirect URI
`<web-origin>/api/operator/auth/callback` at the issuer. The issuer must support
S256 and RS256 ID tokens with `auth_time`. API: configure the same issuer and
audience, and exactly one of `NOVALTON_OPERATOR_OIDC_PUBLIC_KEY_PEM` or a
same-origin HTTPS `NOVALTON_OPERATOR_OIDC_JWKS_URI`. Provision the verified
human subject binding and per-workspace membership/grants through the existing
trusted service. Optional `NOVALTON_OPERATOR_WORKSPACE_SCOPES` is a comma list
of `tenant-uuid:workspace-uuid`, up to ten; the backend still decides access.
No public provisioning route exists. Dispatch stays disabled by default.

The OIDC transaction is replay-resistant through state, nonce, one-use
authorization code and consumed cookie. Clearing the browser cookie does not
revoke an independently copied ID token before its at-most-one-hour expiry;
binding, membership and grant revocation still fence new authority immediately.
Deployment must protect the transaction secret and provider credentials and
serve the web origin over HTTPS. An external IdP was not configured or tested
here; the OIDC exchange tests use a local mocked issuer and ephemeral RS256 key.

The OpenRouter issues #40/#41 transport and structured generation fixes were
inspected and remain intact. No provider key or explicit paid-call budget was
configured: **LIVE_ACCEPTANCE_BLOCKED_CREDENTIALS_OR_BUDGET**. No remote
generation, fresh live workflow or external sign-in was claimed. An unknown
generation identifier after a timeout cannot be reconciled with the above API
and is never treated as free. There is still no strict invoice ceiling or
exactly-once billing guarantee. The reconciler is internal and must be invoked
by a trusted operation with a valid credential; it is not a public or automatic
background route.

## Verification and next work

Web tests exercise transaction tampering/freshness, state, nonce, PKCE, RS256
signature, origin checks and the existing console controls. Build, lint,
typecheck and npm audit passed locally. Three isolated Python JWKS/metadata
tests passed; local PostgreSQL is unavailable, so CI must prove the new
migration, row-lock concurrency, full API suite and I-044A/B. `next start`
could not open a listener in this restricted container (`uv_interface_addresses`
error); no live browser session was observed. Record final CI run IDs and
artifact ID in the release report after publication.

Next: configure and validate an actual IdP over HTTPS, complete a browser/API
journey with real human identity, review ID-token sign-out/revocation and
session storage for stronger stolen-token controls, authorize a tiny paid
OpenRouter acceptance budget and model, reconcile its generation ID, and run a
longer bounded worker workload with crash and heartbeat loss. Keep the Mission 6
QA claim/attempt fence and leave the production daemon disabled.
