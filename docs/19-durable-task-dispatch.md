# Controlled durable task dispatch

Status: controlled operator foundation, Missions 3–5. No daemon or
model-callable scheduling tool is installed. A narrow credential-authenticated
human route controls dispatch decisions; worker execution remains a trusted
internal entry point. Live-provider acceptance is outstanding.

## Execution and activation

The module `novalton_api.modules.durable_dispatch` binds a scheduling record to an
existing, never-started scoped `WorkflowRun`. It never creates execution from a
`Task.status` change. It calls `orchestrator.service.advance` exactly once per
claim; Manager, Developer, QA, Policy, approvals and tools retain their existing
execution and permission contracts.

Two independent controls are required to claim autonomous work:

1. Server configuration `NOVALTON_DURABLE_DISPATCH_ENABLED=true` (default false).
2. A verified operator calls `service.configure_workspace(..., enabled=True)`.

An operator presents a high-entropy credential to `authenticate_operator`; the
server compares its SHA-256 digest in constant time with
`NOVALTON_DISPATCH_OPERATOR_KEY_SHA256`. The server also requires configured
operator ID, durable user UUID, tenant ID, workspace ID and explicit permission
names under `NOVALTON_DISPATCH_OPERATOR_*`. A UUID alone never authenticates the
caller. Migration `20261021_0035` adds a durable human principal and explicit
per-workspace permission rows. Each decision rechecks the active user, label and
exact permission under shared PostgreSQL locks until commit. A concurrent
revocation waits for an in-flight decision and bars subsequent ones. Credential
rotation needs configuration reload in each process; workspace activation
revocation is the distributed worker claim fence.

Permissions are `activation.configure`, `dispatch.enqueue`, `dispatch.read`,
`dispatch.cancel` and `dispatch.resolve`. Activation, enqueue, cancel and
resolution decisions append scoped records with the verified user UUID.
Every activation change increments a generation. Disabling and re-enabling a
workspace cannot restore an old claim. Use the workspace control to revoke
authority across running processes; an environment variable is process-local
configuration, not a distributed revocation signal.

The `/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/dispatch` routes
accept only the configured bearer credential and recheck database membership
through the service layer. Missing credentials and forged identity headers fail
closed. The routes expose activation, requests, bounded attempts, cost evidence,
cancellation and explicit fresh-workflow resolution. They do not run a provider.
Provisioning the user and permissions is a trusted deployment task; no signup,
password, session or grant-management route was added. TLS and credential
custody belong to deployment.

After the existing database/profile checks and Alembic migration, the operator
can use the application's existing session and configured provider registry:

```python
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from novalton_api.modules.durable_dispatch import service
from novalton_api.modules.durable_dispatch.operator import authenticate_operator
from novalton_api.modules.durable_dispatch.schemas import DispatchRequest

operator = authenticate_operator(credential_from_trusted_secret_store)
await service.configure_workspace(
    session, operator=operator, tenant_id=tenant_id, workspace_id=workspace_id, enabled=True
)
record = await service.enqueue(
    session,
    operator=operator,
    tenant_id=tenant_id,
    workspace_id=workspace_id,
    data=DispatchRequest(
        workflow_run_id=explicit_fresh_workflow_id,
        request_key="operator-request-001",
        priority=10,
        deadline=datetime.now(UTC) + timedelta(hours=1),
        max_attempts=8,
        max_model_calls=24,
        allow_unknown_cost=False,
    ),
)
result = await service.run_once(
    session,
    registry=existing_provider_registry,
    tenant_id=tenant_id,
    workspace_id=workspace_id,
    owner=uuid4(),
    heartbeat_session_factory=database.session_factory,
)
```

No activation has been performed on a development or production workspace during
Mission 3. CI activation applies only to disposable test fixtures.

## Persistence and isolation

Migration `20261020_0033` follows the reviewed I-044 migration. It adds
`dispatch_activations`, `task_dispatches`, `dispatch_dependencies` and
`dispatch_attempts`. Composite foreign keys bind tenant/workspace/project/task/run,
and dependency edges cannot cross workspace boundaries. Migration `20261020_0034`
also binds step evidence to its exact workflow with a composite foreign key.
One workflow has one
immutable dispatch binding; a partial unique index allows only one active
READY/LEASED/WAITING_HUMAN dispatch per task.

The request key is unique per tenant/workspace. Identical canonical immutable
input returns the existing record, including after execution; different input
conflicts. Dependencies are supplied only at enqueue and must already exist.
This append-only construction cannot create a cycle through the trusted API.
A new execution requires a fresh explicitly created workflow, not re-enqueueing
an interrupted or failed workflow.

Claims use PostgreSQL `FOR UPDATE SKIP LOCKED`, aged priority, eligible time
and stable ID. Claim generation, attempt count, owner, lease and attempt evidence
commit together before `advance`. A competing worker can select an independent
task without waiting for the locked row. Observation is bounded to 32 records
per tick and rotates its update timestamp to avoid starving later recovery.
READY priority gains one point for each five seconds waiting, capped at 200.
This lets an old -100 request reach the rank of newly arriving +100 requests
after 1,000 seconds; eligible time and ID break ties. It is a bounded fairness
policy, not a production throughput or latency guarantee.

## Fences, budgets and actual effects

A trusted claim context is checked at existing workflow, model and tool
reservation boundaries. A direct advance cannot bypass an unexpired claim.
Owner, generation, activation generation, database-clock lease and deadline are
rechecked transactionally. A late producer can record the true provider/tool
outcome but cannot reserve another model, tool, handoff or continuation after
revocation. Queue leases do not claim to cancel an upstream HTTP request or an
already engaged filesystem operation.

The reservation lock order is AgentRun (when applicable), workflow advisory
fence, activation, dispatch. Queue claims/reconciliation never acquire workflow
or AgentRun locks while holding queue rows. Network work holds no queue lock.

Budgets are 0–64 dispatch attempts, 0–128 model calls and an explicit deadline
within seven days. A model reservation and its counter commit in the same
transaction as `ModelRun`; failed inserts roll back both. Initial calls,
truncation recovery, contract repair and human-approved continuations all consume
the same budget. Zero capacity blocks new work. Exhausted model capacity blocks
new model and ToolCall reservations; persisting the real result of an already
engaged operation remains allowed.

Unknown catalog pricing is refused unless the operator explicitly sets
`allow_unknown_cost=True`. Unknown actual cost stays NULL. These are count and
time budgets, not a monetary ceiling or an exactly-once billing promise. Existing
output-token ceilings, finite correction limits, exact mutation approvals,
I-042 commit proofs and I-043 publication reconciliation are unchanged.

`list_cost_exposure` reports bounded ModelRun evidence: observed cost, estimate
overrun, unknown actual cost, or uncertain external outcome. A lost response or
FAILED/CANCELLED invocation is never classified as free. This is observation,
not an atomic monetary reservation or a provider billing guarantee.

Heartbeats and completion require the exact scoped owner/generation. A heartbeat
never shortens an existing lease or exceeds the deadline. The default lease is
one hour. The controlled runner can renew it during a single iteration through
an independent database session, at an interval no longer than one third of the
lease. A failed renewal marks its in-process claim lost and bars further
reservations. A worker crash or unknown renewal leaves persisted LEASED evidence
that becomes BLOCKED after expiration, without replay. No permanent heartbeat
service is started. A shorter operator-selected lease may stop a long iteration.

`run_batch` is an explicit, at-most-64-iteration internal prototype. A stop
signal prevents the next claim and lets the active tick persist its real result;
each tick uses a fresh session, owner and optional heartbeat, and calls the
existing `orchestrator.service.advance` once. No background service is installed.

## Recovery and human decisions

An expired LEASED dispatch becomes BLOCKED, even if the crash occurred before
`advance`. It is never made READY for another owner. The attempt records a bounded
reason; existing ModelRun/ToolCall evidence remains truthful, including RUNNING
when external completion is unknown. Old owners cannot heartbeat or finalize a
later generation.

Persisted workflow truth determines DONE/CANCELLED/FAILED classification. A
returned success label alone cannot make a dispatch DONE. A task awaiting an
exact approval or unresolved challenge becomes WAITING_HUMAN and releases its
claim. Independent READY tasks can continue.

Only the existing human approval/challenge endpoints can resolve those decisions.
A subsequent tick observes the same workflow and readies it only after the
waiting/running step is resolved and a runnable agent step exists. It never
approves, chooses a correction, replays a mutation, commits or publishes for the
human. Repeated old approvals do not consume another queue claim.

An authorized operator may inspect bounded scoped dispatches/attempts and cancel
the actual workflow; cancellation projects the exact queue row even in a large
queue. `resolve_blocked` requires an old FAILED/CANCELLED workflow and a new,
explicit, never-started WorkflowRun for the same task. It audits the decision
and delegates to normal enqueue. It never reopens an uncertain attempt or
manufactures an approval. Concurrent identical decisions share the new binding.

## Validation and remaining work

Disposable PostgreSQL tests cover concurrent claims/ticks, SKIP LOCKED, canonical
enqueue idempotency, foreign-key isolation, dependencies/priorities, crash before
advance, crash after provider reservation, late responses after lease/deadline/
activation revocation, stale owner/generation, budget rollback, bounded model
repair, exhausted tool authority, independent work during exact approval,
workflow cancellation, real persisted QA PASS/FAIL, and migration history refusal.

Ruff, the complete API suite, frontend checks and the existing installed I-044
acceptance remain required gates. See the Mission 4 handoff for actual run IDs
and results; this document does not substitute for those proofs.

Next work: live-provider acceptance with explicitly available credentials;
operator-facing integration/authentication before exposing these internal APIs;
capacity/load and starvation tests before aging or larger queues; a reviewed
monetary reservation policy if needed. Only after recovery/isolation acceptance
should a long-running worker, UI or automatic activation be considered.
