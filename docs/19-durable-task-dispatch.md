# Controlled durable task dispatch

Status: foundation implementation, Mission 3. No daemon, timer, public scheduling
route or model-callable scheduling tool is installed. The operator must invoke
one iteration explicitly. Live-provider acceptance is still outstanding.

## Execution and activation

The module `novalton_api.modules.durable_dispatch` binds a scheduling record to an
existing, never-started scoped `WorkflowRun`. It never creates execution from a
`Task.status` change. It calls `orchestrator.service.advance` exactly once per
claim; Manager, Developer, QA, Policy, approvals and tools retain their existing
execution and permission contracts.

Two independent controls are required to claim autonomous work:

1. Server configuration `NOVALTON_DURABLE_DISPATCH_ENABLED=true` (default false).
2. A trusted operator calls `service.configure_workspace(..., enabled=True)`.

These are internal trusted Python entry points, not HTTP/agent permissions.
Activation and enqueue decisions append scoped audit records atomically.
Every activation change increments a generation. Disabling and re-enabling a
workspace cannot restore an old claim. Use the workspace control to revoke
authority across running processes; an environment variable is process-local
configuration, not a distributed revocation signal.

After the existing database/profile checks and Alembic migration, the operator
can use the application's existing session and configured provider registry:

```python
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from novalton_api.modules.durable_dispatch import service
from novalton_api.modules.durable_dispatch.schemas import DispatchRequest

await service.configure_workspace(
    session, tenant_id=tenant_id, workspace_id=workspace_id, enabled=True
)
record = await service.enqueue(
    session,
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
)
```

No activation has been performed on a development or production workspace during
Mission 3. CI activation applies only to disposable test fixtures.

## Persistence and isolation

Migration `20261020_0033` follows the reviewed I-044 migration. It adds
`dispatch_activations`, `task_dispatches`, `dispatch_dependencies` and
`dispatch_attempts`. Composite foreign keys bind tenant/workspace/project/task/run,
and dependency edges cannot cross workspace boundaries. One workflow has one
immutable dispatch binding; a partial unique index allows only one active
READY/LEASED/WAITING_HUMAN dispatch per task.

The request key is unique per tenant/workspace. Identical canonical immutable
input returns the existing record, including after execution; different input
conflicts. Dependencies are supplied only at enqueue and must already exist.
This append-only construction cannot create a cycle through the trusted API.
A new execution requires a fresh explicitly created workflow, not re-enqueueing
an interrupted or failed workflow.

Claims use PostgreSQL `FOR UPDATE SKIP LOCKED`, priority descending, eligible time
and stable ID. Claim generation, attempt count, owner, lease and attempt evidence
commit together before `advance`. A competing worker can select an independent
task without waiting for the locked row. Observation is bounded to 32 records
per tick and rotates its update timestamp to avoid starving later recovery.

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

Heartbeats and completion require the exact scoped owner/generation. A heartbeat
never shortens an existing lease or exceeds the deadline. The default lease is
one hour; the controlled runner does not spawn a heartbeat thread. A shorter
operator-selected lease may stop a long iteration, safely and without retry.

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
