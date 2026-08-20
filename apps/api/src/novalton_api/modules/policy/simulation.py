"""Read-only policy simulation over the authoritative decision path."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.policy import service
from novalton_api.modules.policy.schemas import (
    PolicyEvaluationRequest,
    PolicySimulationRequest,
    PolicySimulationResult,
)


async def simulate(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    data: PolicySimulationRequest,
) -> PolicySimulationResult:
    """Evaluate one proposed action without audit, approval, events, or execution."""
    request = PolicyEvaluationRequest(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        action=data.action,
        actor_type=data.actor_type,
        actor_id=data.actor_id,
        resource_type=data.resource_type,
        resource_id=data.resource_id,
        project_id=data.project_id,
        task_id=data.task_id,
        context=data.context,
    )
    decision = await service.evaluate_decision(session, request=request)
    return PolicySimulationResult(**decision.model_dump())
