"""Policy scope validation, persistence, evaluation, and audit integration."""

import logging
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.policy import repository
from novalton_api.modules.policy.evaluator import EvaluationRule, evaluate_rules
from novalton_api.modules.policy.models import PolicyRule
from novalton_api.modules.policy.schemas import (
    PolicyEvaluationRequest,
    PolicyEvaluationResult,
    PolicyRuleCreate,
)
from novalton_api.modules.projects import repository as projects_repository
from novalton_api.modules.tasks import repository as tasks_repository
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id

logger = logging.getLogger(__name__)


def _not_found() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


async def _require_workspace(session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID) -> None:
    if (
        await get_workspace_by_tenant_and_id(
            session, tenant_id=tenant_id, workspace_id=workspace_id
        )
        is None
    ):
        raise _not_found()


async def create_rule(session: AsyncSession, *, data: PolicyRuleCreate) -> PolicyRule:
    """Persist one validated rule after enforcing workspace ownership."""
    try:
        if not await repository.tenant_exists(session, tenant_id=data.tenant_id):
            raise _not_found()
        if data.workspace_id is not None:
            await _require_workspace(
                session, tenant_id=data.tenant_id, workspace_id=data.workspace_id
            )
        rule = await repository.create_rule(
            session,
            tenant_id=data.tenant_id,
            workspace_id=data.workspace_id,
            name=data.name,
            enabled=data.enabled,
            action_pattern=data.action_pattern,
            effect=data.effect.value,
            actor_type=data.actor_type,
            resource_type=data.resource_type,
            conditions_json=[condition.model_dump(mode="json") for condition in data.conditions],
        )
        await session.commit()
        await session.refresh(rule)
        return rule
    except ApplicationError:
        await session.rollback()
        raise
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.error(
            "Policy persistence failed",
            extra={"event": "policy.persistence_failed", "exception_type": type(exc).__name__},
        )
        raise ApplicationError(
            "policy_persistence_failed", "Policy rule could not be persisted", status_code=500
        ) from None


async def _validate_evaluation_scope(
    session: AsyncSession, request: PolicyEvaluationRequest
) -> None:
    await _require_workspace(
        session, tenant_id=request.tenant_id, workspace_id=request.workspace_id
    )
    if request.project_id is not None:
        project = await projects_repository.get_project(
            session, workspace_id=request.workspace_id, project_id=request.project_id
        )
        if project is None:
            raise _not_found()
    if request.task_id is not None:
        task = await tasks_repository.get_task(
            session, project_id=request.project_id, task_id=request.task_id
        )
        if task is None:
            raise _not_found()


async def evaluate(
    session: AsyncSession, *, request: PolicyEvaluationRequest
) -> PolicyEvaluationResult:
    """Evaluate effective tenant/workspace rules and audit non-silent outcomes."""
    result = await evaluate_decision(session, request=request)
    if result.audit_required:
        outcome = "blocked" if result.effect.value == "BLOCK" else "success"
        await append_record(
            session,
            data=AuditRecordCreate(
                tenant_id=request.tenant_id,
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                task_id=request.task_id,
                action="policy.evaluate",
                actor_type="service",
                actor_id=None,
                outcome=outcome,
                metadata={
                    "action": request.action,
                    "final_effect": result.effect.value,
                    "matched_rule_ids": [str(rule_id) for rule_id in result.matched_rule_ids],
                    "matched_rule_count": len(result.matched_rule_ids),
                },
            ),
            commit=True,
        )
    return result


async def evaluate_decision(
    session: AsyncSession, *, request: PolicyEvaluationRequest
) -> PolicyEvaluationResult:
    """Return the authoritative policy decision without integration side effects."""
    await _validate_evaluation_scope(session, request)
    records = await repository.list_applicable_rules(
        session, tenant_id=request.tenant_id, workspace_id=request.workspace_id
    )
    rules = [
        EvaluationRule(
            id=rule.id,
            name=rule.name,
            action_pattern=rule.action_pattern,
            effect=rule.effect,
            actor_type=rule.actor_type,
            resource_type=rule.resource_type,
            conditions=rule.conditions_json,
        )
        for rule in records
    ]
    return evaluate_rules(request, rules)
