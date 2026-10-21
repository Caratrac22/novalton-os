# Novalton OS — Mission 7 handoff

Branch `feature/mission7-saas-financial`, stacked on PR #95 at
`818491f509e9cd4a8392a02ea3228065102d5ee0`. Do not merge any stacked
PR into main without authorization. Verify the latest PR checks and export
artifact before using this branch as a new base.

## Implemented

- An explicit tenant membership now narrows the existing credential-verified
  human principal and exact workspace grants. Decisions and worker reservations
  reread and lock both membership and grant from PostgreSQL with
  `populate_existing`, including reused SQLAlchemy sessions. A trusted internal
  operation revokes membership with an audit record. Rotation provisions a
  fresh UUID, membership and grants in one transaction. A migration backfills
  existing scoped operators as members without granting new workspaces.
- Dispatch requests may optionally specify `max_estimated_exposure` in USD.
  Before each ModelRun, the existing dispatch row serializes reservations with
  its row lock. The calculation uses the complete catalog context window and
  the larger of the requested output budget or catalog maximum (up to the API
  ceiling), rounded upward. It requires both prices and catalog verification
  within 24 hours. The reserved amount, tariff verification time and price
  snapshot persist with the ModelRun. Reservations survive errors, lost
  responses and crashes; no refund is inferred.
- Cost evidence names catalog-priced token usage accurately. The legacy
  `ModelRun.actual_cost` field is a calculation from observed tokens and the
  saved catalog prices; it is **not** independently verified provider billing.
  The operator response includes explicit `provider_billing_verified: false`.
- The existing complete-workflow benchmark remains intact. A second bounded
  workload adds progressive arrivals and varied deterministic provider delays,
  measuring completed Manager → Developer → QA workflows and end-to-end
  latency. It does not use a paid provider.
- GitHub Actions now builds, verifies and uploads a complete Mission 7 Git
  bundle, source ZIP and SHA-256 manifest after both CI jobs pass.

## Security and financial limits

The dispatch switch remains off by default. No public provisioning endpoint,
password system, OAuth adapter, long-running daemon, model shell or new
privilege was introduced. A single configured credential and principal per
process still constrain operator usability; there is no general SaaS session
or trusted identity adapter for the Next.js application yet. The minimal
browser operator flow remains disabled until that boundary exists.

The estimated exposure limit coordinates *catalog-based reservations* for
one dispatch. It does not cap a provider invoice: the price can change after
catalog verification, actual prompt token accounting can differ, an upstream
provider can charge differently, and no external billing reconciliation or
idempotency contract is available. Unknown or stale prices are rejected when
this optional budget is enabled. The existing count/deadline budget and
default refusal of unknown pricing remain in force for all dispatches.
Uncertain provider calls remain charged to their reservation, never zeroed.
No strict monetary spending guarantee is claimed.

The OpenRouter transport already sends `Accept-Encoding: identity`, and the
structured response format contract exists; these were inspected against
issues #40 and #41. No authorized credential plus explicit live budget was
available. **LIVE_ACCEPTANCE_BLOCKED_CREDENTIALS_OR_BUDGET**. A fresh isolated
workflow and a separately approved minimal generation are still needed for
real provider acceptance; never replay an old failed workflow.

## Validation and recovery

Local Python compilation, Ruff formatting/lint and `git diff --check` passed
before publication. Local PostgreSQL and pytest are unavailable; GitHub
Actions on disposable `novalton_test` is the authoritative integration gate.
The Mission 7 PR's latest successful CI and I-044A/B runs, including their
run IDs and measured `dispatch_complete`/`dispatch_progressive` output, must
be recorded here after completion. Do not infer production capacity from
these short CI workloads. The recovery artifact must contain `HEAD.txt`,
`COMMITS.txt`, `SHA256SUMS`, `MISSION_8_REPRISE.md`, the full `.bundle`, and
the source `.zip`. Check artifact HEAD against the PR head.

## Next

Introduce a reviewed external authentication/session adapter that constructs
a trusted ActorContext; map human memberships and service identities without
accepting caller asserted headers. Keep the workspace grant as an explicit
narrowing gate. Build a server mediated Next.js operator view only after that
adapter is verified. Obtain a provider billing contract and price freshness
semantics before any strict spend policy; then run separately budgeted live
acceptance. Extend sustained workload to worker interruption, heartbeat loss,
pending human decisions and restart in one reproducible scenario, retaining
the Mission 6 QA claim/attempt reconciliation fence.
