# Novalton OS — Mission 6 handoff for Mission 7

Branch `feature/mission6-full-workflows`, PR #95 stacked on Mission 5 PR #94
at `28cfe289c1ca203d3cd0cbef1ed1d0b308bcb6ef`. Neither PR is merged
into `main`. Check the final recovery package's `HEAD.txt` and successful CI
and I-044 checks before treating the branch as validated.

## Implemented

- An isolated PostgreSQL workload drives the existing dispatcher and
  `orchestrator.service.advance` through actual Manager, Developer and QA
  transitions, using a deterministic local provider. Ten, 25 and 50 workflow
  cases use six concurrent workers. The test counts completed workflows and
  ModelRuns and measures end-to-end latency separately from claim throughput.
  There is no simulated human approval in these success cases.
- The first concurrent run exposed a terminal reconciliation race: another
  worker could persist DONE for the QA claim before its owner finalized it.
  The runner now recognizes completion only with the same dispatch generation,
  owner, step, terminal attempt and completed workflow. Other lost claims still
  fail closed. A deterministic regression forces this ordering.
- A trusted internal provisioning service rotates a scoped operator to a fresh
  durable UUID. It validates the current credential-backed human and all
  delegated grants under exclusive PostgreSQL locks, provisions the successor,
  revokes the old scoped grants and records an audit decision in one transaction.
  A competing rotation cannot produce two accepted successors. A separate
  operation revokes one scoped permission. No public administration route or
  model-callable authority was added.
- Credentials and digests are never stored by provisioning. Deployment must
  provision a fresh secret securely and switch process configuration to the
  new user UUID and label **after** the old grants are revoked. Downtime during
  rotation is preferable to an overlap that reauthorizes a stale process. A
  process with the old configuration cannot make a new claim or effect
  reservation after the transaction commits; an already sent provider result
  retains its actual ModelRun evidence.

## Evidence and limits

Read the final CI job's `dispatch_complete` lines for measured throughput and
p50/p95/p99 end-to-end latency. The provider is deterministic and local; these
numbers measure real workflow and database transitions, not external model
latency, sustained production fairness or an SLA. Existing tests separately
cover priority aging, dependencies, waiting humans, cancellation, heartbeat
loss, uncertainty and restart without replay.

Issue #70's general SaaS membership and authentication provider remain separate
from this deliberately narrow operator credential. There is no password/session
product or self-service grant route. The configured operator is currently one
principal per process and scope.

The Model Router's `estimated_cost` uses estimated context and expected output;
`GenerationResult` contains token usage, **not an authoritative billed amount**.
Catalog prices and output limits can be absent or stale, and the provider has
no documented idempotent billing/reconciliation contract here. A transactionally
reserved estimate would not be a sound monetary ceiling. The count/deadline
budgets, default rejection of unknown catalog prices and cost evidence remain;
uncertain requests are never classified as free. An enforceable monetary policy
needs reviewed provider billing/usage bounds or an external reconciliation
source. Do not present estimates as a spend guarantee.

Issues #40/#41 and the OpenRouter structured-output transport have simulated
tests. No authorized endpoint, credential and explicit paid-call budget were
present in this session: `LIVE_ACCEPTANCE_BLOCKED_CREDENTIALS_OR_BUDGET`.
There was no actual remote Manager → Developer → QA acceptance. No daemon or
production continuous worker was activated. The existing `run_batch` remains
an explicit bounded prototype, with dispatch off by default.

## Recovery

Use the PR's latest successful CI `Verified Git recovery export`: it clones a
complete Git bundle and checks the exact HEAD/tree, then publishes a source ZIP,
SHA-256 sums and this report. Verify the artifact and checks before restoring;
do not substitute Mission 5's bundle for this branch. Mission 7 should add a
reviewed monetary billing contract and reservation policy, integrate general
SaaS identity without broad insecure routes, and perform a separately budgeted
live acceptance before considering a permanent worker.
