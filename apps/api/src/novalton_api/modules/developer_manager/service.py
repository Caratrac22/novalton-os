"""Scoped Developer Manager definition and I-022 execution integration."""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.modules.agents import execution, repository
from novalton_api.modules.agents.models import AgentDefinition
from novalton_api.modules.agents.schemas import AgentDefinitionStatus
from novalton_api.modules.developer_manager.contracts import DeveloperManagerResult
from novalton_api.modules.developer_manager.schemas import (
    DeveloperManagerPlanningRequest,
    DeveloperManagerPlanningResponse,
)

logger = logging.getLogger(__name__)
DEVELOPER_MANAGER_SLUG = "developer_manager"
DEVELOPER_MANAGER_NAME = "Developer Manager"
DEVELOPER_MANAGER_CATEGORY = "development"
DEVELOPER_MANAGER_MISSION = (
    "Coordinate bounded software-development decomposition and review recommendations "
    "without executing work or exercising orchestration or policy authority."
)
DEVELOPER_MANAGER_CAPABILITIES = [
    "code_review_planning",
    "implementation_planning",
    "software_architecture",
    "task_decomposition",
]
_CONTRACT_INSTRUCTIONS = (
    "The development_plan is advisory only. Do not request actions, tools, shell or Git "
    "execution, spawn workers, mutate workflows, grant permissions or approvals, select a "
    "provider/model, or include executable payloads."
)


async def resolve_definition(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID
) -> AgentDefinition:
    definition = await repository.latest_definition(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        slug=DEVELOPER_MANAGER_SLUG,
    )
    if definition is None:
        raise ApplicationError(
            "developer_manager_unavailable", "Developer Manager is unavailable", status_code=404
        )
    if definition.status != AgentDefinitionStatus.ENABLED.value:
        raise ApplicationError(
            "developer_manager_unavailable", "Developer Manager is unavailable", status_code=409
        )
    return definition


async def plan(
    session: AsyncSession,
    *,
    registry: ProviderRegistry,
    tenant_id: UUID,
    workspace_id: UUID,
    data: DeveloperManagerPlanningRequest,
) -> DeveloperManagerPlanningResponse:
    definition = await resolve_definition(session, tenant_id=tenant_id, workspace_id=workspace_id)
    response = await execution.execute(
        session,
        registry=registry,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        definition_id=definition.id,
        data=data,
        result_contract=DeveloperManagerResult,
        contract_instructions=_CONTRACT_INSTRUCTIONS,
    )
    result = response.result
    if result is not None:
        assert isinstance(result, DeveloperManagerResult)
        logger.info(
            "Developer Manager proposal validated",
            extra={
                "event": "developer_manager.proposal.validated",
                "tenant_id": str(tenant_id),
                "workspace_id": str(workspace_id),
                "agent_definition_id": str(definition.id),
                "agent_version": definition.version,
                "agent_run_id": str(response.agent_run_id),
                "proposal_task_count": len(result.development_plan.proposed_tasks),
                "challenge_level": result.challenge.level.value,
            },
        )
    return DeveloperManagerPlanningResponse(
        agent_run_id=response.agent_run_id,
        agent_definition_id=response.agent_definition_id,
        agent_definition_version=response.agent_definition_version,
        status=response.status,
        selected_model=response.selected_model,
        model_run_id=response.model_run_id,
        result=result,
        error_code=response.error_code,
    )
