# Novalton OS — Mission 5 handoff for Mission 6

Branch `feature/mission5-identity-capacity`, PR #94 stacked on Mission 4 PR
#93 at `997bc8a0584e654199db8e672433380b180128b9`. Neither PR was merged
into `main`. The recovery package's `HEAD.txt` identifies the final commit;
read its attached CI and I-044A/B checks before treating this report as accepted.

## Implemented

- Migration `20261021_0035` adds a durable human operator and explicit
  tenant/workspace/permission grants. A configured high-entropy credential is
  pinned to that user's UUID; every service decision rechecks active identity,
  matching label, scope and exact grant with PostgreSQL shared locks. Revocation
  of a user or permission blocks subsequent decisions and waits for an in-flight
  one. No workspace UUID, arbitrary actor header or unverified role is authority.
- Narrow bearer-authenticated routes provide activation, enqueue, bounded reads,
  cancellation and fresh-workflow resolution. No HTTP route executes a worker,
  registers a credential or manages grants. Audit decisions carry the verified
  user UUID. Provisioning is an explicit trusted deployment step; there is no
  password, OAuth, SaaS session store or tenant-wide membership inheritance.
- Each new worker claim and provider/tool reservation rechecks the configured
  activating human and active workspace activation grant under database locks.
  Revoking that grant stops subsequent reservations. A provider call already
  engaged may still persist its real result before the next claim is denied.
- A bounded read of linked ModelRun evidence distinguishes known observed cost,
  unknown actual cost, estimate overrun and uncertain external outcome. A failed,
  cancelled or lost response is never assumed free. There is still **no atomic
  monetary spend reservation or exactly-once provider billing guarantee**.
- A controlled `run_batch` performs at most 64 existing `run_once` iterations
  through fresh sessions/owners; it uses `orchestrator.service.advance`, respects
  an explicit stop signal between ticks and preserves the existing claim fences.
  There is no daemon, periodic poller or automatic production activation.

## Evidence and scope

The intermediate identity/capacity checkpoint passed 829 API tests on disposable
PostgreSQL 16, Ruff, migrations, frontend and Python audit in CI run
`39577273806`; the final HEAD has its own checks. The queue-only synthetic
workload used no provider. Its six-worker measurements were:

| Tasks | Claims/s | p50 | p95 | p99 | Collisions | PostgreSQL errors | Uncertain blocked |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 50 | 87.49 | 53.38 ms | 133.03 ms | 139.84 ms | 0 | 0 | 50 |
| 100 | 102.59 | 50.23 ms | 100.96 ms | 137.09 ms | 0 | 0 | 100 |
| 200 | 101.06 | 49.24 ms | 70.67 ms | 281.43 ms | 0 | 0 | 200 |

The elapsed claim times were 0.571, 0.975 and 1.979 seconds respectively.
Ten tasks arrived after workers began in each run. All expired claims remained
blocked, with one attempt apiece and no replay. This measures reservations and
recovery of synthetic records, **not completed workflow throughput, sustained
production fairness or provider latency**. Existing controlled tests separately
cover human waits, budget exhaustion, cancellation during generation, heartbeat
loss, restart and late responses. The bounded batch test reuses simulated
Manager → Developer → QA outcomes.

Issues #40/#41 and the OpenRouter structured-output contract were rechecked.
Transport tests cover identity encoding, response format, malformed JSON,
HTTP errors, timeout, response bounds and interrupted stream handling. In this
session the endpoint and API credential were absent, and no paid-call budget was
authorized: `LIVE_ACCEPTANCE_BLOCKED_CREDENTIALS`. No live provider call or
live Manager → Developer → QA proof occurred.

## Recovery and next decisions

CI's `Verified Git recovery export` job builds a complete Git bundle and tracked
source ZIP from the final HEAD, verifies a clone's exact tree and HEAD, and
uploads them with SHA-256 sums and `MISSION_6_REPRISE.md`. Confirm the final
successful artifact and checks before restoring. Do not use the old Mission 4
bundle as a substitute for the Mission 5 branch.

Dispatch remains default off. Credential rotation requires process config reload;
workspace activation generation remains the distributed worker fence. Before
routine or continuous deployment: integrate reviewed credential provisioning
and TLS, test sustained full-workflow processing and fairness, define a safe
monetary reservation/reconciliation policy or provider idempotency, and perform
an explicitly budgeted live acceptance with a fresh isolated workflow. Keep
human approvals and I-044A/B security contracts as independent authorities.
