"""Trusted operator entry points: enqueue and execute at most one existing advance."""

import hashlib
import json
from datetime import UTC, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.modules.durable_dispatch import repository
from novalton_api.modules.durable_dispatch.authority import (
    DispatchClaim,
    current_claim,
    database_now,
    denied,
)
from novalton_api.modules.durable_dispatch.models import (
    DispatchActivation,
    DispatchDependency,
    TaskDispatch,
)
from novalton_api.modules.durable_dispatch.schemas import DispatchRequest
from novalton_api.modules.orchestrator import service as orchestrator_service
from novalton_api.modules.orchestrator.schemas import OrchestrationResult
from novalton_api.modules.workflows.cancellation import lock_workflow
from novalton_api.modules.workflows.models import WorkflowRun, WorkflowStepRun
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id


async def configure_workspace(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, enabled: bool
) -> DispatchActivation:
    """Operator-only library API, never exposed as an agent tool or public route.

    Every explicit change rotates activation generation, including disable then
    re-enable. An old claim can never regain authority from a new activation.
    """
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
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, data: DispatchRequest
) -> TaskDispatch:
    """Bind a fresh explicit WorkflowRun; never create a workflow from task metadata."""
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
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise denied("dispatch_binding_conflict") from None
    return row


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
) -> OrchestrationResult | None:
    """One bounded observation/claim and one advance; no loop, replay or approvals.

    A process death after claim deliberately leaves LEASED evidence. A later
    tick BLOCKS an expired attempt; even a crash before advance cannot retry it.
    """
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
        finished = await repository.finish(session, claimed)
        if not finished:
            await repository.reconcile(session, tenant_id=tenant_id, workspace_id=workspace_id)
        raise
    else:
        finished = await repository.finish(session, claimed, result=result)
        if not finished:
            await repository.reconcile(session, tenant_id=tenant_id, workspace_id=workspace_id)
        return result
    finally:
        current_claim.reset(token)
