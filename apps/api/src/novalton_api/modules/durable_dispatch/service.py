"""Trusted operator entry points: enqueue and execute at most one existing advance."""

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.durable_dispatch import repository
from novalton_api.modules.durable_dispatch.authority import (
    DispatchClaim,
    current_claim,
    database_now,
    denied,
)
from novalton_api.modules.durable_dispatch.models import (
    DispatchActivation,
    DispatchAttempt,
    DispatchDependency,
    TaskDispatch,
)
from novalton_api.modules.durable_dispatch.operator import OperatorAuthority
from novalton_api.modules.durable_dispatch.schemas import DispatchRequest
from novalton_api.modules.orchestrator import service as orchestrator_service
from novalton_api.modules.orchestrator.schemas import OrchestrationResult
from novalton_api.modules.workflows.cancellation import lock_workflow
from novalton_api.modules.workflows.models import WorkflowRun, WorkflowStepRun
from novalton_api.modules.workflows.service import cancel_run
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id


async def configure_workspace(
    session: AsyncSession,
    *,
    operator: OperatorAuthority,
    tenant_id: UUID,
    workspace_id: UUID,
    enabled: bool,
) -> DispatchActivation:
    """Operator-only library API, never exposed as an agent tool or public route.

    Every explicit change rotates activation generation, including disable then
    re-enable. An old claim can never regain authority from a new activation.
    """
    operator.require("activation.configure", tenant_id=tenant_id, workspace_id=workspace_id)
    workspace = await get_workspace_by_tenant_and_id(
        session, tenant_id=tenant_id, workspace_id=workspace_id
    )
    if workspace is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    if type(enabled) is not bool:
        raise ValueError("enabled must be boolean")
    now = await database_now(session)
    row = await session.scalar(
        insert(DispatchActivation)
        .values(
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            enabled=enabled,
            generation=1,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=[DispatchActivation.workspace_id],
            set_={
                "enabled": enabled,
                "generation": DispatchActivation.generation + 1,
                "updated_at": now,
            },
            where=DispatchActivation.tenant_id == tenant_id,
        )
        .returning(DispatchActivation)
        .execution_options(populate_existing=True)
    )
    if row is None:
        await session.rollback()
        raise denied("dispatch_scope_mismatch")
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            action="dispatch.activation.configure",
            actor_type="local_user",
            actor_id=operator.actor_id,
            outcome="success",
            metadata={"enabled": enabled, "generation": row.generation},
        ),
        commit=False,
    )
    await session.commit()
    return row


def _fingerprint(data: DispatchRequest) -> str:
    payload = data.model_dump(mode="json")
    payload["deadline"] = data.deadline.astimezone(UTC).isoformat()
    payload["eligible_at"] = (
        data.eligible_at.astimezone(UTC).isoformat() if data.eligible_at else None
    )
    payload["dependencies"] = sorted(str(identifier) for identifier in data.dependencies)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


async def enqueue(
    session: AsyncSession,
    *,
    operator: OperatorAuthority,
    tenant_id: UUID,
    workspace_id: UUID,
    data: DispatchRequest,
) -> TaskDispatch:
    """Bind a fresh explicit WorkflowRun; never create a workflow from task metadata."""
    operator.require("dispatch.enqueue", tenant_id=tenant_id, workspace_id=workspace_id)
    await lock_workflow(session, data.workflow_run_id)
    run = await session.scalar(
        select(WorkflowRun)
        .where(
            WorkflowRun.id == data.workflow_run_id,
            WorkflowRun.tenant_id == tenant_id,
            WorkflowRun.workspace_id == workspace_id,
        )
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    configured = await repository.activation(
        session, tenant_id=tenant_id, workspace_id=workspace_id, exclusive=True
    )
    if configured is None:
        raise denied("dispatch_activation_required")
    fingerprint = _fingerprint(data)
    existing = await session.scalar(
        select(TaskDispatch)
        .where(
            TaskDispatch.tenant_id == tenant_id,
            TaskDispatch.workspace_id == workspace_id,
            TaskDispatch.request_key == data.request_key,
        )
        .execution_options(populate_existing=True)
    )
    if existing is not None:
        if existing.input_fingerprint != fingerprint:
            raise denied("dispatch_request_conflict")
        await session.commit()
        return existing
    started = await session.scalar(
        select(WorkflowStepRun.id)
        .where(
            WorkflowStepRun.workflow_run_id == run.id,
            (WorkflowStepRun.agent_run_id.is_not(None))
            | (WorkflowStepRun.status.not_in(["READY", "PENDING"])),
        )
        .limit(1)
    )
    if run.status != "CREATED" or started is not None:
        raise denied("dispatch_fresh_workflow_required")
    now = await database_now(session)
    if data.deadline <= now or data.deadline > now + timedelta(days=7):
        raise denied("dispatch_deadline_invalid")
    if data.dependencies:
        identifiers = set(
            await session.scalars(
                select(TaskDispatch.id).where(
                    TaskDispatch.id.in_(data.dependencies),
                    TaskDispatch.tenant_id == tenant_id,
                    TaskDispatch.workspace_id == workspace_id,
                )
            )
        )
        if identifiers != set(data.dependencies):
            raise denied("dispatch_dependency_scope_mismatch")
    row = TaskDispatch(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=run.project_id,
        task_id=run.task_id,
        workflow_run_id=run.id,
        request_key=data.request_key,
        input_fingerprint=fingerprint,
        priority=data.priority,
        eligible_at=data.eligible_at or now,
        deadline=data.deadline,
        status="READY",
        max_attempts=data.max_attempts,
        max_model_calls=data.max_model_calls,
        allow_unknown_cost=data.allow_unknown_cost,
    )
    session.add(row)
    try:
        await session.flush()
        for identifier in data.dependencies:
            session.add(
                DispatchDependency(
                    dispatch_id=row.id,
                    prerequisite_id=identifier,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                )
            )
        await append_record(
            session,
            data=AuditRecordCreate(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                project_id=run.project_id,
                task_id=run.task_id,
                resource_type="task",
                resource_id=run.task_id,
                action="dispatch.task.enqueue",
                actor_type="local_user",
                actor_id=operator.actor_id,
                outcome="success",
                metadata={
                    "dispatch_id": str(row.id),
                    "workflow_run_id": str(run.id),
                    "max_attempts": row.max_attempts,
                    "max_model_calls": row.max_model_calls,
                    "allow_unknown_cost": row.allow_unknown_cost,
                },
            ),
            commit=False,
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise denied("dispatch_binding_conflict") from None
    return row


async def list_dispatches(
    session: AsyncSession,
    *,
    operator: OperatorAuthority,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int = 50,
) -> list[TaskDispatch]:
    """Bounded scoped observation, never a scheduling decision."""
    operator.require("dispatch.read", tenant_id=tenant_id, workspace_id=workspace_id)
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    return list(
        await session.scalars(
            select(TaskDispatch)
            .where(TaskDispatch.tenant_id == tenant_id, TaskDispatch.workspace_id == workspace_id)
            .order_by(TaskDispatch.created_at.desc(), TaskDispatch.id)
            .limit(limit)
        )
    )


async def list_attempts(
    session: AsyncSession,
    *,
    operator: OperatorAuthority,
    tenant_id: UUID,
    workspace_id: UUID,
    dispatch_id: UUID,
    limit: int = 50,
) -> list[DispatchAttempt]:
    operator.require("dispatch.read", tenant_id=tenant_id, workspace_id=workspace_id)
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    row = await session.scalar(
        select(TaskDispatch.id).where(
            TaskDispatch.id == dispatch_id,
            TaskDispatch.tenant_id == tenant_id,
            TaskDispatch.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    return list(
        await session.scalars(
            select(DispatchAttempt)
            .where(DispatchAttempt.dispatch_id == dispatch_id)
            .order_by(DispatchAttempt.generation.desc())
            .limit(limit)
        )
    )


async def cancel_dispatch(
    session: AsyncSession,
    *,
    operator: OperatorAuthority,
    tenant_id: UUID,
    workspace_id: UUID,
    dispatch_id: UUID,
) -> TaskDispatch:
    """Cancel the actual workflow under its fence, then project queue state."""
    operator.require("dispatch.cancel", tenant_id=tenant_id, workspace_id=workspace_id)
    binding = await session.scalar(
        select(TaskDispatch.workflow_run_id).where(
            TaskDispatch.id == dispatch_id,
            TaskDispatch.tenant_id == tenant_id,
            TaskDispatch.workspace_id == workspace_id,
        )
    )
    if binding is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    await lock_workflow(session, binding)
    row = await session.scalar(
        select(TaskDispatch)
        .where(TaskDispatch.id == dispatch_id, TaskDispatch.workflow_run_id == binding)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    recorded = await session.scalar(
        select(AuditRecord.id).where(
            AuditRecord.tenant_id == tenant_id,
            AuditRecord.workspace_id == workspace_id,
            AuditRecord.action == "dispatch.task.cancel",
            AuditRecord.metadata_json["dispatch_id"].astext == str(row.id),
        )
    )
    if row.status != "CANCELLED" and recorded is None:
        await append_record(
            session,
            data=AuditRecordCreate(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                project_id=row.project_id,
                task_id=row.task_id,
                resource_type="task",
                resource_id=row.task_id,
                action="dispatch.task.cancel",
                actor_type="local_user",
                actor_id=operator.actor_id,
                outcome="success",
                metadata={"dispatch_id": str(row.id), "workflow_run_id": str(binding)},
            ),
            commit=False,
        )
    await cancel_run(session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=binding)
    settled = await repository.reconcile_cancelled(
        session, tenant_id=tenant_id, workspace_id=workspace_id, dispatch_id=dispatch_id
    )
    assert settled is not None
    return settled


async def resolve_blocked(
    session: AsyncSession,
    *,
    operator: OperatorAuthority,
    tenant_id: UUID,
    workspace_id: UUID,
    blocked_id: UUID,
    data: DispatchRequest,
) -> TaskDispatch:
    """Explicit decision to use a new workflow; the old attempt is never replayed."""
    operator.require("dispatch.resolve", tenant_id=tenant_id, workspace_id=workspace_id)
    operator.require("dispatch.enqueue", tenant_id=tenant_id, workspace_id=workspace_id)
    previous = await session.scalar(
        select(TaskDispatch).where(
            TaskDispatch.id == blocked_id,
            TaskDispatch.tenant_id == tenant_id,
            TaskDispatch.workspace_id == workspace_id,
            TaskDispatch.status.in_(["BLOCKED", "CANCELLED"]),
        )
    )
    if previous is None:
        raise denied("dispatch_resolution_unavailable")
    previous_status = await session.scalar(
        select(WorkflowRun.status).where(WorkflowRun.id == previous.workflow_run_id)
    )
    fresh = await session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.id == data.workflow_run_id,
            WorkflowRun.tenant_id == tenant_id,
            WorkflowRun.workspace_id == workspace_id,
            WorkflowRun.project_id == previous.project_id,
            WorkflowRun.task_id == previous.task_id,
        )
    )
    if previous_status not in {"CANCELLED", "FAILED"} or fresh is None:
        raise denied("dispatch_resolution_requires_terminal_old_and_fresh_run")
    # Serialize duplicate decisions with enqueue's workflow fence. Only the
    # transaction which creates the new binding records the human decision.
    await lock_workflow(session, data.workflow_run_id)
    existing = await session.scalar(
        select(TaskDispatch.id).where(
            TaskDispatch.tenant_id == tenant_id,
            TaskDispatch.workspace_id == workspace_id,
            TaskDispatch.request_key == data.request_key,
        )
    )
    if existing is not None:
        return await enqueue(
            session, operator=operator, tenant_id=tenant_id, workspace_id=workspace_id, data=data
        )
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=previous.project_id,
            task_id=previous.task_id,
            resource_type="task",
            resource_id=previous.task_id,
            action="dispatch.task.resolve",
            actor_type="local_user",
            actor_id=operator.actor_id,
            outcome="success",
            metadata={"previous_dispatch_id": str(blocked_id), "new_workflow_run_id": str(fresh.id)},
        ),
        commit=False,
    )
    return await enqueue(
        session,
        operator=operator,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data=data,
    )


async def claim_next(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    owner: UUID,
    lease_seconds: int = 3600,
) -> DispatchClaim | None:
    if not get_settings().durable_dispatch_enabled:
        raise denied("dispatch_disabled")
    return await repository.claim(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner=owner,
        lease_seconds=lease_seconds,
    )


async def run_once(
    session: AsyncSession,
    *,
    registry: ProviderRegistry,
    tenant_id: UUID,
    workspace_id: UUID,
    owner: UUID,
    lease_seconds: int = 3600,
    heartbeat_session_factory: async_sessionmaker[AsyncSession] | None = None,
    heartbeat_interval_seconds: float | None = None,
) -> OrchestrationResult | None:
    """One bounded observation/claim and one advance; no loop, replay or approvals.

    A process death after claim deliberately leaves LEASED evidence. A later
    tick BLOCKS an expired attempt; even a crash before advance cannot retry it.
    """
    if heartbeat_session_factory is None and heartbeat_interval_seconds is not None:
        raise ValueError("heartbeat interval requires an independent session factory")
    if heartbeat_session_factory is not None:
        interval = heartbeat_interval_seconds or min(60.0, lease_seconds / 3)
        if not 0 < interval <= lease_seconds / 3:
            raise ValueError("heartbeat interval must be positive and at most a third of lease")
    else:
        interval = None
    await repository.reconcile(session, tenant_id=tenant_id, workspace_id=workspace_id)
    claimed = await claim_next(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner=owner,
        lease_seconds=lease_seconds,
    )
    if claimed is None:
        return None
    lost = asyncio.Event()
    stopped = asyncio.Event()
    claimed = replace(claimed, lost=lost)

    async def renew() -> None:
        assert heartbeat_session_factory is not None and interval is not None
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            try:
                async with heartbeat_session_factory() as renewal_session:
                    valid = await repository.heartbeat(
                        renewal_session, claimed, lease_seconds=lease_seconds
                    )
            except Exception:
                # A database error is uncertain. Stop in-process authority;
                # the persisted lease will eventually become BLOCKED.
                lost.set()
                return
            if not valid:
                lost.set()
                return

    renewal = asyncio.create_task(renew()) if heartbeat_session_factory is not None else None
    token = current_claim.set(claimed)
    try:
        result = await orchestrator_service.advance(
            session,
            registry=registry,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            workflow_run_id=claimed.workflow_run_id,
        )
    except Exception:
        # Keep only a bounded reason; never persist raw exceptions or provider content.
        await session.rollback()
        if not lost.is_set():
            finished = await repository.finish(session, claimed)
            if not finished:
                await repository.reconcile(session, tenant_id=tenant_id, workspace_id=workspace_id)
        raise
    else:
        if lost.is_set():
            raise denied("dispatch_claim_lost")
        finished = await repository.finish(session, claimed, result=result)
        if not finished:
            await repository.reconcile(session, tenant_id=tenant_id, workspace_id=workspace_id)
            raise denied("dispatch_claim_lost")
        return result
    finally:
        stopped.set()
        if renewal is not None:
            await renewal
        current_claim.reset(token)
