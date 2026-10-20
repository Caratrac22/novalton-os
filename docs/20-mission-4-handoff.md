# Novalton OS — Mission 4 handoff for Mission 5

Date: 2026-10-20. This report follows the Mission 3 HEAD
`57de4a40bdab4735a747c2af8baf518f86a3d367` and describes the Mission 4
branch `feature/mission4-operator-dispatch`, PR
[#93](https://github.com/Caratrac22/novalton-os/pull/93), stacked on PR #92.
Neither #93 nor its ancestors were merged into `main`; no force push was used.
The recovery package's `HEAD.txt` identifies the exact final documentation HEAD.

## Implemented

- An internal, scoped operator capability authenticates a high-entropy credential
  against a configured SHA-256 digest. Activation, enqueue, bounded reads,
  cancellation and explicit resolution each require a separately named permission.
  Every call checks current configured identity, scope and permissions; operator
  changes are audited with the configured actor ID. No public dispatch route or
  model-callable control was exposed. An operator integration must still supply
  and protect the credential; a tenant/workspace UUID is never authentication.
- Repeated cancellation projects the exact dispatch after the existing workflow
  cancellation fence. An operator may resolve a BLOCKED/CANCELLED dispatch only
  after the old workflow is terminal, with a new explicit fresh WorkflowRun for
  the same task. The old uncertain attempt is never replayed; concurrent identical
  resolution decisions bind one new dispatch and record one decision.
- READY claims use bounded age-adjusted priority and PostgreSQL `SKIP LOCKED`.
  A controlled single-iteration runner optionally renews a claim using an
  independent session at no more than one third of its lease duration. Failed
  renewal revokes in-process reservation authority; an uncertain crash remains
  LEASED until reconciliation BLOCKS it. Claims retain owner/generation fencing.
- PostgreSQL tests exercise distinct workers, 18 independent tasks with six
  claimers, priority aging, crash recovery, lost heartbeat, late response,
  cancellation, isolation, permissions and a three-tick Manager → Developer → QA
  progression with an independent blocked task. The capacity test prints elapsed
  claim time, collision count and recovery count in CI output. It is a controlled
  capacity smoke test, not a production load or latency guarantee.

The existing `orchestrator.service.advance` remains the only execution engine.
Approvals, exact mutation permissions, I-042 proofs and I-044A/B sandbox
contracts retain their existing authorities. Default dispatch configuration is
off; no permanent worker, public scheduling API or automatic activation exists.
No Mission 4 migration is needed; the Mission 3 migrations `20261020_0033` and
`20261020_0034` continue to provide the persisted schema.

## Validation and limits

The final CI, I-044 and export identifiers must be taken from the successful
checks attached to PR #93 at the recovery package's HEAD. Earlier checks on
intermediate commits do not establish acceptance of the final tree. Tests run
against disposable PostgreSQL 16 `novalton_test` in GitHub Actions. This local
session has Python 3.12 without the project test dependencies or PostgreSQL;
local syntax compilation and `git diff --check` are supplemental only.

Issues #40 and #41 were examined. Existing OpenRouter code uses identity content
encoding and passes structured JSON intent to the transport, with simulated
provider tests. There was no configured OpenRouter endpoint/credential or an
approved paid-call budget in this session. No real provider request was sent;
the live Manager → Developer → QA acceptance remains blocked, and the simulated
path must not be presented as live proof. No secret belongs in logs or archives.

The in-process credential config has per-process reload/rotation semantics;
workspace activation generation is the persisted distributed revocation fence.
The controlled heartbeat does not cancel an already sent provider request.
Crash-time external billing is uncertain without provider reconciliation or
idempotency; model-call count, attempt and deadline bounds are not a monetary
ceiling. The 18-task test does not prove sustained multi-worker throughput,
database contention or fairness under a continuous production arrival stream.

## Recovery and next mission

The PR's `Verified Git recovery export` Action, after backend and frontend gates,
creates a complete bundle, a tracked-source ZIP, `HEAD.txt`, `COMMITS.txt`, this
handoff as `MISSION_5_REPRISE.md`, and `SHA256SUMS` with 90-day retention.
Verify the checksums, `git bundle verify`, and the restored tree against
`HEAD.txt`; inspect PR #92/#93 before working from the branch. Never replay a
BLOCKED uncertain attempt or infer an approval from dispatch state.

Mission 5 should connect the internal operator service to a reviewed human
identity source, add sustained workload and fairness measurement with bounded
database capacity, demonstrate a budgeted real provider path when credentials
and approval are available, and review monetary reservations/reconciliation.
Only then consider a permanent worker or automatic operations.
