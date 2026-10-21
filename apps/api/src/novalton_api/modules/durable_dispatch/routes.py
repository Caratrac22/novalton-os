"""Narrow credential-authenticated human controls; no worker execution endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.durable_dispatch import service
from novalton_api.modules.durable_dispatch.cost_evidence import list_cost_exposure
from novalton_api.modules.durable_dispatch.models import TaskDispatch
from novalton_api.modules.durable_dispatch.operator import OperatorAuthority, authenticate_operator
from novalton_api.modules.durable_dispatch.schemas import DispatchRequest
from novalton_api.modules.durable_dispatch.sessions import authenticate_session
from novalton_api.modules.workflows.operator_view import get_operator_view

router = APIRouter(prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/dispatch")
Session = Annotated[AsyncSession, Depends(get_async_session)]


class ActivationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


async def verified_operator(
    tenant_id: UUID,
    workspace_id: UUID,
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> OperatorAuthority:
    if authorization is None or not authorization.startswith("Bearer "):
        raise ApplicationError(
            "dispatch_auth_required", "Operator credential required", status_code=401
        )
    credential = authorization.removeprefix("Bearer ")
    if not credential or credential != credential.strip() or " " in credential:
        raise ApplicationError(
            "dispatch_auth_required", "Operator credential required", status_code=401
        )
    if credential.count(".") == 2:
        return await authenticate_session(
            session, token=credential, tenant_id=tenant_id, workspace_id=workspace_id
        )
    return authenticate_operator(credential)


Operator = Annotated[OperatorAuthority, Depends(verified_operator)]


def _record(row) -> dict[str, object]:
    return {
        "id": row.id,
        "workflow_run_id": row.workflow_run_id,
        "task_id": row.task_id,
        "priority": row.priority,
        "deadline": row.deadline,
        "lease_expires_at": row.lease_expires_at,
        "status": row.status,
        "generation": row.generation,
        "attempt_count": row.attempt_count,
        "model_call_count": row.model_call_count,
        "max_estimated_exposure": row.max_estimated_exposure,
        "reserved_estimated_exposure": row.reserved_estimated_exposure,
        "stop_reason": row.stop_reason,
    }


@router.post("/activation")
async def activation(
    tenant_id: UUID, workspace_id: UUID, data: ActivationInput, session: Session, operator: Operator
):
    row = await service.configure_workspace(
        session,
        operator=operator,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        enabled=data.enabled,
    )
    return {"enabled": row.enabled, "generation": row.generation}


@router.post("/requests", status_code=201)
async def enqueue(
    tenant_id: UUID, workspace_id: UUID, data: DispatchRequest, session: Session, operator: Operator
):
    return _record(
        await service.enqueue(
            session, operator=operator, tenant_id=tenant_id, workspace_id=workspace_id, data=data
        )
    )


@router.get("/requests")
async def list_requests(
    tenant_id: UUID, workspace_id: UUID, session: Session, operator: Operator, limit: int = 50
):
    return [
        _record(row)
        for row in await service.list_dispatches(
            session, operator=operator, tenant_id=tenant_id, workspace_id=workspace_id, limit=limit
        )
    ]


@router.get("/requests/{dispatch_id}/attempts")
async def attempts(
    tenant_id: UUID,
    workspace_id: UUID,
    dispatch_id: UUID,
    session: Session,
    operator: Operator,
    limit: int = 50,
):
    return [
        {
            "generation": row.generation,
            "outcome": row.outcome,
            "reason_code": row.reason_code,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }
        for row in await service.list_attempts(
            session,
            operator=operator,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            dispatch_id=dispatch_id,
            limit=limit,
        )
    ]


@router.get("/requests/{dispatch_id}/workflow")
async def workflow_evidence(
    tenant_id: UUID,
    workspace_id: UUID,
    dispatch_id: UUID,
    session: Session,
    operator: Operator,
):
    await operator.require_human(
        session, "dispatch.read", tenant_id=tenant_id, workspace_id=workspace_id
    )
    workflow_id = await session.scalar(
        select(TaskDispatch.workflow_run_id).where(
            TaskDispatch.id == dispatch_id,
            TaskDispatch.tenant_id == tenant_id,
            TaskDispatch.workspace_id == workspace_id,
        )
    )
    if workflow_id is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    return await get_operator_view(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        workflow_run_id=workflow_id,
    )


@router.get("/requests/{dispatch_id}/cost-evidence")
async def costs(
    tenant_id: UUID, workspace_id: UUID, dispatch_id: UUID, session: Session, operator: Operator
):
    return [
        {
            "model_run_id": item.model_run_id,
            "model_definition_id": item.model_definition_id,
            "status": item.status,
            "classification": item.classification,
            "estimated_cost": item.estimated_cost,
            "catalog_priced_usage": item.catalog_priced_usage,
            "reserved_estimated_exposure": item.reserved_estimated_exposure,
            "price_verified_at_snapshot": item.price_verified_at_snapshot,
            "input_price_per_million_snapshot": item.input_price_per_million_snapshot,
            "output_price_per_million_snapshot": item.output_price_per_million_snapshot,
            "provider_billing_verified": False,
            "provider_billing_status": "PROVIDER_REPORTED_USAGE"
            if item.provider_reported_cost is not None
            else "BILLING_UNVERIFIED",
            "provider_generation_id": item.provider_generation_id,
            "provider_reported_cost": item.provider_reported_cost,
            "provider_reported_at": item.provider_reported_at,
            "provider_report_exceeds_reservation": item.provider_report_exceeds_reservation,
            "currency": item.currency,
        }
        for item in await list_cost_exposure(
            session,
            operator=operator,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            dispatch_id=dispatch_id,
        )
    ]


@router.post("/requests/{dispatch_id}/cancel")
async def cancel(
    tenant_id: UUID, workspace_id: UUID, dispatch_id: UUID, session: Session, operator: Operator
):
    return _record(
        await service.cancel_dispatch(
            session,
            operator=operator,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            dispatch_id=dispatch_id,
        )
    )


@router.post("/requests/{dispatch_id}/resolve", status_code=201)
async def resolve(
    tenant_id: UUID,
    workspace_id: UUID,
    dispatch_id: UUID,
    data: DispatchRequest,
    session: Session,
    operator: Operator,
):
    return _record(
        await service.resolve_blocked(
            session,
            operator=operator,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            blocked_id=dispatch_id,
            data=data,
        )
    )
