# Mission 10 handoff — controlled integration

Branch `feature/mission10-integrated-acceptance` starts at the verified PR #98
HEAD `6cdc978fe5dace98ff11d8d38d0c62ca7eb04268`. PR #99 was closed at
the operator's request and is not an ancestor or base of this work. No merge or
force-push is authorized. Verify the new PR head, CI, installed I-044 gates and
export artifact before continuing.

## Executed and changed

- A local HTTPS OIDC issuer and TLS reverse proxy now exercise the production
  Next.js server routes, including S256 PKCE, state, nonce, code exchange,
  RS256 session cookie, console list/detail, workspace selection, Origin
  checks, cancellation, logout, callback replay and an unauthorized backend
  response. The upstream in this smoke is explicitly a **signed-token
  validating test stub**, with deterministic workflow and cost evidence; it is
  neither an external identity provider nor PostgreSQL/FastAPI. The smoke
  runs in the CI frontend job after the production build.
- The first live server smoke uncovered a real reverse-proxy callback failure:
  Next's `request.url` included its internal port, so an exact origin check
  rejected the valid public HTTPS callback. The callback now checks the
  configured public `Host` and forwarded HTTPS protocol and reconstructs the
  configured public redirect URL with the received query. State, signed
  five-minute transaction cookie, nonce, PKCE, issuer, audience, token
  signature and expiry remain enforced. Deploy only behind a trusted TLS
  reverse proxy that sets and overwrites forwarding headers; the proxy must
  prevent direct untrusted access to the Next listener.
- A separate disposable-PostgreSQL test follows a signed human identity through
  FastAPI dispatch listing, three real Manager/Developer/QA advances with the
  existing deterministic local provider, persisted ModelRuns and attempts,
  workflow and cost evidence, idempotent cancellation, forbidden tenant scope,
  and subject revocation. It does not run a browser or the external OIDC
  issuer.
- A second, continuous CI acceptance starts a local HTTPS issuer, real Next
  server and real FastAPI server against `novalton_test`. A trusted test
  provisioner binds the issuer's public key and subject to the fixture human
  before releasing the OIDC callback. The workflow already advanced with the
  deterministic local provider appears in the console; a second fresh work
  item is cancelled through Next and FastAPI. PostgreSQL verifies the decision,
  then revocation causes the still-present browser cookie to lose backend
  authority. The client uses HTTP requests and a cookie jar rather than a
  graphical browser engine; all server routes and database operations are real.

## Validation boundaries

Local Node smoke passed with a local HTTPS issuer and test API. The 17 existing
web tests, ESLint, typecheck, production build and Python Ruff/compilation
passed. No local PostgreSQL executable is available; the two database tests,
including the continuous HTTP journey, all migrations and complete API suite
require the disposable `novalton_test` CI profile. Record final run IDs, test
count and failures after publishing; the continuous test is not claimed as
passed until its CI run succeeds.
The smoke initially failed and drove the proxy fix; a stale generated Next
cache had to be moved aside before a fresh build picked up the change.

Issues #40 and #41 were inspected. Identity encoding and structured JSON
output remain present. No OpenRouter credential and explicit paid-call budget
are available: **LIVE_ACCEPTANCE_BLOCKED_CREDENTIALS_OR_BUDGET**. No remote
generation or actual external sign-in occurred. Provider usage observations
remain distinct from catalog estimates and independently verified billing;
`BILLING_UNVERIFIED` is preserved absent authenticated evidence. No daemon
was enabled, and no live provider was used for load tests.

PRs #88, #91, #92, #93, #94, #95, #96, #97 and #98 were inspected without
mutation. They are open, unmerged and marked mergeable; each base SHA equals
the preceding head, and the repository has linear migration ancestry. Review
and integrate in that order only after human approval, rechecking CI and
mergeability at each step. A "mergeable" snapshot is not a promise against
future conflicts. Keep #99 closed and out of the ancestry.

## Next acceptance work

Run one graphical HTTPS browser session against a trusted external development
IdP, real Next, FastAPI, disposable PostgreSQL and a provisioned human binding
in the same environment. Test token theft/logout revocation requirements separately:
clearing a browser cookie alone does not revoke a copied ID token before its
expiry; membership and grant revocation still fence authority. Then, with
separately approved model and spend budget, perform a new minimal OpenRouter
generation and a fresh workflow, reconcile its exact generation ID and retain
unknown-cost outcomes. Continue bounded worker recovery tests and leave
production autonomous dispatch disabled by default.
