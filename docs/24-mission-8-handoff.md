# Mission 8 handoff

Branch `feature/mission8-session-operator` is stacked on Mission 7 PR #96 at
`ae8f4f28535b0e1c66fab68a190b52edd927a6a0`. No stacked PR was merged.

## Implemented

- A pinned RS256 public key validates a short-lived external identity token
  against configured HTTPS issuer, audience, signature, issue time, expiration
  and human `auth_time`. A durable `(issuer, subject)` binding maps only to an
  existing `HumanOperator`. A tenant membership and exact workspace permission
  are rechecked and locked for each decision, including SQLAlchemy session
  reuse. Revoking the binding bars future session decisions; membership/grant
  revocation continues to fence dispatch reservations as in Missions 5–7.
- Internal audited bind and revoke methods require `activation.configure`.
  They are not public administration routes. A service token without a human
  authentication time fails. Identity gateway/deployment is responsible for
  authenticating people, issuing the token and setting the same-origin Secure,
  HttpOnly, SameSite `__Host-novalton-operator-session` cookie. No application
  login route, password store or issuer key retrieval was introduced.
- The Next.js `/operator` view reads bounded dispatch requests. Each detail
  page reads a separately authorized backend workflow view, ModelRuns, cost
  classifications and attempt history. Cancellation and fresh-workflow
  resolution call the governed dispatch service through a server route, with
  explicit HTTPS Origin matching. An unavailable session or permission shows
  an unavailable state. The backend still enforces every decision.
- Migration `20261021_0038` stores the federated subject binding; it guards
  downgrades containing history. Existing dispatch and QA reconciliation
  fences are unchanged.
- A bounded deterministic workload stops two workers after six committed
  provider steps, then completes ten Manager → Developer → QA workflows with
  four fresh workers. It verifies exactly three attempts and ModelRuns per
  workflow and measures completed-workflow latency across the turnover. This
  tests restart at committed boundaries, not process death during a network
  invocation or long-duration production endurance.

## Configuration and limits

Set `NOVALTON_OPERATOR_OIDC_ISSUER`, `NOVALTON_OPERATOR_OIDC_AUDIENCE` and
`NOVALTON_OPERATOR_OIDC_PUBLIC_KEY_PEM` on the API. The trusted login gateway
must issue RS256 tokens with `iss`, `aud`, `sub`, `iat`, `exp` and `auth_time`,
lasting at most one hour, and set the `__Host-` cookie on the web origin.
Set `NOVALTON_WEB_ORIGIN` to its exact HTTPS origin for mutations. Provision
the subject with the internal binding service after confirming the person and
membership out of band. No arbitrary identity header or service account is a
substitute. The dispatch activation/configuration gates remain off by default.

There is no configured identity gateway or live login session in this
environment. The web path can be tested with signed local fixture tokens, but
must not be described as a completed real human sign-in. The fixed public key
requires a coordinated deployment rotation; a JWKS rotation and managed login
integration remain future work.

Financial evidence is still a catalog estimate and observed token calculation.
There is no authenticated provider invoice or reconciliation identifier
contract. `BILLING_UNVERIFIED` remains the truthful status; no strictly
enforceable invoice ceiling or exactly-once billing is claimed. No live
provider endpoint, credential or explicit budget was configured:
`LIVE_ACCEPTANCE_BLOCKED_CREDENTIALS_OR_BUDGET`.

## Validation and next steps

Local Python compilation, `git diff --check` and the isolated web Origin test
passed. API/PostgreSQL migrations, full suite, Ruff, frontend build/audits and
I-044A/B require the GitHub Actions test profile. Record exact run IDs and
results after publication; do not infer green checks from this document.

Next: deploy and review an identity gateway with key rotation, cookie custody
and real human login; collect a provider-authenticated invoice source before
enabling billing verification; run a separately authorized minimal OpenRouter
generation then a fresh Manager → Developer → QA workflow; extend the existing
bounded workload to longer restart and heartbeat-loss scenarios. Keep the
permanent daemon disabled and preserve the Mission 6 QA attempt fence.
