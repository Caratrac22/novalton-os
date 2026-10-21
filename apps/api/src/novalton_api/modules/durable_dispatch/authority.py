"""Reservation fencing shared by the trusted model/tool/workflow boundaries."""

from asyncio import Event
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.durable_dispatch.models import (
    DispatchActivation,
    DispatchAttempt,
    TaskDispatch,
)
from novalton_api.modules.durable_dispatch.operator import require_active_dispatch_operator
from novalton_api.modules.workflows.models import WorkflowStepRun


@dataclass(frozen=True)
class DispatchClaim:
    dispatch_id: UUID
    tenant_id: UUID
    workspace_id: UUID
    workflow_run_id: UUID
    owner: UUID
    generation: int
    activation_generation: int
    lost: Event | None = None


current_claim: ContextVar[DispatchClaim | None] = ContextVar("durable_dispatch_claim", default=None)


def denied(code: str) -> ApplicationError:
    return ApplicationError(code, "Durable dispatch authority is unavailable", status_code=409)


async def database_now(session: AsyncSession) -> datetime:
    return (await session.execute(select(func.clock_timestamp()))).scalar_one()


async def binding_for_reservation(
    session: AsyncSession, workflow_run_id: UUID
) -> TaskDispatch | None:
    """Lock activation then binding; callers already own the workflow fence.

    No transaction spans provider I/O. An expired LEASED binding is never
    transferable to another producer, including a direct/manual advance.
    """
    claim = current_claim.get()
    if claim is not None and claim.lost is not None and claim.lost.is_set():
        raise denied("dispatch_claim_lost")
    if claim is not None and claim.workflow_run_id != workflow_run_id:
        raise denied("dispatch_scope_mismatch")
    scope = (
        await session.execute(
            select(TaskDispatch.id, TaskDispatch.tenant_id, TaskDispatch.workspace_id).where(
                TaskDispatch.workflow_run_id == workflow_run_id
            )
        )
    ).first()
    if scope is None:
        if claim is not None:
            raise denied("dispatch_scope_mismatch")
        return None
    identifier, tenant_id, workspace_id = scope
    await require_active_dispatch_operator(
        session, tenant_id=tenant_id, workspace_id=workspace_id
    )
    activation = await session.scalar(
        select(DispatchActivation)
        .where(
            DispatchActivation.tenant_id == tenant_id,
            DispatchActivation.workspace_id == workspace_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    row = await session.scalar(
        select(TaskDispatch)
        .where(TaskDispatch.id == identifier)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = await database_now(session)
    if row is None or row.status in {"BLOCKED", "DONE", "CANCELLED"}:
        raise denied("dispatch_not_runnable")
    if row.deadline <= now:
        raise denied("dispatch_deadline_exhausted")
    if row.max_attempts == 0:
        raise denied("dispatch_attempt_budget_exhausted")
    if row.max_model_calls == 0:
        raise denied("dispatch_model_budget_exhausted")
    if claim is None:
        if row.status == "LEASED":
            raise denied("dispatch_claim_required")
        return row
    if (
        not get_settings().durable_dispatch_enabled
        or activation is None
        or not activation.enabled
        or activation.generation != claim.activation_generation
    ):
        raise denied("dispatch_disabled")
    if (
        row.id != claim.dispatch_id
        or (row.tenant_id, row.workspace_id) != (claim.tenant_id, claim.workspace_id)
        or row.status != "LEASED"
        or row.owner != claim.owner
        or row.generation != claim.generation
        or row.activation_generation != claim.activation_generation
        or row.lease_expires_at is None
        or row.lease_expires_at <= now
    ):
        raise denied("dispatch_claim_lost")
    return row


async def require_workflow(session: AsyncSession, workflow_run_id: UUID) -> None:
    await binding_for_reservation(session, workflow_run_id)


async def reserve_model(session: AsyncSession, *, agent_run_id: UUID, price_known: bool) -> None:
    workflow_run_id = await session.scalar(
        select(WorkflowStepRun.workflow_run_id).where(WorkflowStepRun.agent_run_id == agent_run_id)
    )
    if workflow_run_id is None:
        if current_claim.get() is not None:
            raise denied("dispatch_scope_mismatch")
        return
    row = await binding_for_reservation(session, workflow_run_id)
    if row is None:
        return
    if row.model_call_count >= row.max_model_calls:
        raise denied("dispatch_model_budget_exhausted")
    if not price_known and not row.allow_unknown_cost:
        raise denied("dispatch_unknown_model_cost")
    row.model_call_count += 1
    row.updated_at = await database_now(session)
    # Counter and ModelRun creation are committed by model_usage.start_run.
    # A rollback consumes neither; a crash after commit never refunds it.
    await session.flush()


async def require_effect_capacity(session: AsyncSession, workflow_run_id: UUID) -> None:
    """Do not reserve a new tool effect after the model budget is exhausted.

    Persisting the real outcome of an already engaged tool/provider remains
    permitted. This check applies only at the new effect reservation boundary.
    """
    row = await binding_for_reservation(session, workflow_run_id)
    if row is not None and row.model_call_count >= row.max_model_calls:
        raise denied("dispatch_model_budget_exhausted")


async def record_step_claim(
    session: AsyncSession, *, workflow_run_id: UUID, step_run_id: UUID
) -> None:
    """Bind crash evidence atomically with the existing READY-to-RUNNING CAS."""
    claimed = current_claim.get()
    if claimed is None:
        return
    if claimed.workflow_run_id != workflow_run_id:
        raise denied("dispatch_scope_mismatch")
    identifier = await session.scalar(
        update(DispatchAttempt)
        .where(
            DispatchAttempt.dispatch_id == claimed.dispatch_id,
            DispatchAttempt.workflow_run_id == workflow_run_id,
            DispatchAttempt.generation == claimed.generation,
            DispatchAttempt.owner == claimed.owner,
            DispatchAttempt.outcome.is_(None),
            DispatchAttempt.workflow_step_run_id.is_(None),
        )
        .values(workflow_step_run_id=step_run_id)
        .returning(DispatchAttempt.id)
    )
    if identifier is None:
        raise denied("dispatch_step_claim_conflict")
