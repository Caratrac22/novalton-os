"""Approval lifecycle, scope validation, policy integration, and transactions."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.context import get_correlation_id
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.approvals import repository
from novalton_api.modules.approvals.models import ApprovalRequest
from novalton_api.modules.approvals.schemas import ApprovalCreate, ApprovalStatus
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.policy import service as policy_service
from novalton_api.modules.policy.schemas import (
    PolicyEffect,
    PolicyEvaluationRequest,
)
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id

logger = logging.getLogger(__name__)


def _not_found() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


def _invalid(message: str) -> ApplicationError:
    return ApplicationError("invalid_approval", message, status_code=422)


def _conflict(message: str) -> ApplicationError:
    return ApplicationError("approval_conflict", message, status_code=409)


async def _require_workspace(session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID) -> None:
    if (
        await get_workspace_by_tenant_and_id(
            session, tenant_id=tenant_id, workspace_id=workspace_id
        )
        is None
    ):
        raise _not_found()


def _evaluation_request(
    *, tenant_id: UUID, workspace_id: UUID, data: ApprovalCreate
) -> PolicyEvaluationRequest:
    return PolicyEvaluationRequest(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        action=data.action,
        actor_type=data.requester_actor_type,
        actor_id=data.requester_actor_id,
        resource_type=data.resource_type,
        resource_id=data.resource_id,
        project_id=data.project_id,
        task_id=data.task_id,
        context=data.context,
    )


def _audit_resource(approval: ApprovalRequest) -> tuple[str | None, UUID | None]:
    if approval.resource_type in {"project", "task"}:
        return approval.resource_type, approval.resource_id
    return None, None


def _audit_data(approval: ApprovalRequest, *, action: str) -> AuditRecordCreate:
    resource_type, resource_id = _audit_resource(approval)
    return AuditRecordCreate(
        tenant_id=approval.tenant_id,
        workspace_id=approval.workspace_id,
        project_id=approval.project_id,
        task_id=approval.task_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        actor_type="local_user" if action != "approval.request" else "service",
        actor_id=None,
        outcome="success",
        correlation_id=approval.correlation_id,
        metadata={
            "approval_id": str(approval.id),
            "action": approval.action,
            "scope_type": approval.scope_type,
            "status": approval.status,
            "matched_rule_count": len(approval.matched_rule_ids),
            "matched_rule_ids": approval.matched_rule_ids,
        },
    )


async def create_approval(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    data: ApprovalCreate,
) -> ApprovalRequest:
    """Re-evaluate and persist authority only when policy requires confirmation."""
    request = _evaluation_request(tenant_id=tenant_id, workspace_id=workspace_id, data=data)
    result = await policy_service.evaluate(session, request=request)
    if result.effect == PolicyEffect.BLOCK:
        raise _invalid("Blocked actions cannot request approval")
    if result.effect != PolicyEffect.REQUIRE_CONFIRMATION:
        raise _invalid("Approval requires a confirmation-required policy decision")

    try:
        approval = await repository.create_approval(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            action=data.action,
            requester_actor_type=data.requester_actor_type,
            requester_actor_id=data.requester_actor_id,
            resource_type=data.resource_type,
            resource_id=data.resource_id,
            project_id=data.project_id,
            task_id=data.task_id,
            status=ApprovalStatus.PENDING.value,
            scope_type="ONE_ACTION",
            policy_effect=result.effect.value,
            matched_rule_ids=[str(rule_id) for rule_id in result.matched_rule_ids],
            policy_reasons=result.reasons,
            correlation_id=get_correlation_id(),
            mutation_fingerprint=data.mutation_fingerprint,
        )
        await append_record(
            session, data=_audit_data(approval, action="approval.request"), commit=False
        )
        await session.commit()
        await session.refresh(approval)
        return approval
    except ApplicationError:
        await session.rollback()
        raise
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.error(
            "Approval persistence failed",
            extra={"event": "approval.persistence_failed", "exception_type": type(exc).__name__},
        )
        raise ApplicationError(
            "approval_persistence_failed",
            "Approval request could not be persisted",
            status_code=500,
        ) from None


async def get_approval(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    approval_id: UUID,
) -> ApprovalRequest:
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    approval = await repository.get_scoped_approval(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        approval_id=approval_id,
    )
    if approval is None:
        raise _not_found()
    return approval


async def list_approvals(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
    status: ApprovalStatus | None,
) -> list[ApprovalRequest]:
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    if not 1 <= limit <= 100 or offset < 0:
        raise _invalid("Approval retrieval bounds are invalid")
    return await repository.list_scoped_approvals(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        status=status.value if status is not None else None,
    )


async def _decide(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    approval_id: UUID,
    target: ApprovalStatus,
) -> ApprovalRequest:
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    try:
        approval = await repository.get_scoped_approval(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            approval_id=approval_id,
            for_update=True,
        )
        if approval is None:
            raise _not_found()
        if approval.status == target.value:
            return approval
        if approval.status != ApprovalStatus.PENDING.value:
            raise _conflict("Approval has already reached a terminal decision")

        decided = await repository.decide_pending(
            session,
            approval_id=approval.id,
            status=target.value,
            decided_at=datetime.now(UTC),
        )
        if decided is None:
            raise _conflict("Approval decision conflicted with another decision")
        audit_action = (
            "approval.approve" if target == ApprovalStatus.APPROVED else "approval.reject"
        )
        await append_record(session, data=_audit_data(decided, action=audit_action), commit=False)
        await session.commit()
        await session.refresh(decided)
        return decided
    except ApplicationError:
        await session.rollback()
        raise
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.error(
            "Approval decision persistence failed",
            extra={"event": "approval.persistence_failed", "exception_type": type(exc).__name__},
        )
        raise ApplicationError(
            "approval_persistence_failed",
            "Approval decision could not be persisted",
            status_code=500,
        ) from None


async def approve(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, approval_id: UUID
) -> ApprovalRequest:
    """Record local single-user human approval without executing the action."""
    return await _decide(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        approval_id=approval_id,
        target=ApprovalStatus.APPROVED,
    )


async def reject(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, approval_id: UUID
) -> ApprovalRequest:
    """Record local single-user human rejection without executing the action."""
    return await _decide(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        approval_id=approval_id,
        target=ApprovalStatus.REJECTED,
    )


def _exact_scope_matches(
    approval: ApprovalRequest,
    request: PolicyEvaluationRequest,
    mutation_fingerprint: str | None = None,
) -> bool:
    return (
        approval.tenant_id == request.tenant_id
        and approval.workspace_id == request.workspace_id
        and approval.action == request.action
        and approval.requester_actor_type == request.actor_type
        and approval.requester_actor_id == request.actor_id
        and approval.resource_type == request.resource_type
        and approval.resource_id == request.resource_id
        and approval.project_id == request.project_id
        and approval.task_id == request.task_id
        and approval.scope_type == "ONE_ACTION"
        and approval.mutation_fingerprint == mutation_fingerprint
    )


async def is_approval_satisfied(
    session: AsyncSession,
    *,
    approval_id: UUID,
    request: PolicyEvaluationRequest,
    mutation_fingerprint: str | None = None,
) -> bool:
    """Check exact prior authority and re-evaluate so a later BLOCK always wins."""
    approval = await repository.get_scoped_approval(
        session,
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        approval_id=approval_id,
    )
    if approval is None or approval.status != ApprovalStatus.APPROVED.value:
        return False
    if not _exact_scope_matches(approval, request, mutation_fingerprint):
        return False
    if not isinstance(approval.matched_rule_ids, list) or not isinstance(
        approval.policy_reasons, list
    ):
        return False
    current = await policy_service.evaluate(session, request=request)
    return current.effect != PolicyEffect.BLOCK
