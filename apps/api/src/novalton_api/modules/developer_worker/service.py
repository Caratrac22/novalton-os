"""Scoped Developer Worker definition and I-022 execution integration."""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.modules.agents import execution, repository
from novalton_api.modules.agents.models import AgentDefinition
from novalton_api.modules.agents.schemas import AgentDefinitionStatus
from novalton_api.modules.developer_worker.contracts import DeveloperWorkerResult
from novalton_api.modules.developer_worker.schemas import (
    DeveloperWorkerExecutionRequest,
    DeveloperWorkerExecutionResponse,
)

logger = logging.getLogger(__name__)
DEVELOPER_WORKER_SLUG = "developer_worker"
DEVELOPER_WORKER_NAME = "Developer Worker"
DEVELOPER_WORKER_CATEGORY = "development"
DEVELOPER_WORKER_MISSION = (
    "Execute one bounded software-development assignment and return a validated "
    "implementation result without mutating repositories or exercising authority."
)
DEVELOPER_WORKER_CAPABILITIES = [
    "code_reasoning",
    "debugging",
    "software_implementation",
    "test_planning",
]
DEVELOPER_WORKER_PERMISSIONS = [
    "workspace.list_files",
    "workspace.read_file",
    "workspace.search_text",
]
_CONTRACT_INSTRUCTIONS = (
    "Return implementation metadata only. A tool_proposals entry may name only an explicitly "
    "permitted server-owned read-only tool; it is a proposal, not provider-native execution or "
    "authority. Do not include code bodies, commands, credentials, provider/model overrides, "
    "approval flags, repository writes, worker delegation, workflow mutations, QA execution, or "
    "executable payloads. Proposed changes do not authorize execution."
)


async def resolve_definition(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID
) -> AgentDefinition:
    definition = await repository.latest_definition(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        slug=DEVELOPER_WORKER_SLUG,
    )
    if definition is None:
        raise ApplicationError(
            "developer_worker_unavailable", "Developer Worker is unavailable", status_code=404
        )
    if definition.status != AgentDefinitionStatus.ENABLED.value:
        raise ApplicationError(
            "developer_worker_unavailable", "Developer Worker is unavailable", status_code=409
        )
    return definition


async def execute_assignment(
    session: AsyncSession,
    *,
    registry: ProviderRegistry,
    tenant_id: UUID,
    workspace_id: UUID,
    data: DeveloperWorkerExecutionRequest,
) -> DeveloperWorkerExecutionResponse:
    definition = await resolve_definition(session, tenant_id=tenant_id, workspace_id=workspace_id)
    response = await execution.execute(
        session,
        registry=registry,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        definition_id=definition.id,
        data=data,
        result_contract=DeveloperWorkerResult,
        contract_instructions=_CONTRACT_INSTRUCTIONS,
    )
    result = response.result
    if result is not None:
        assert isinstance(result, DeveloperWorkerResult)
        logger.info(
            "Developer Worker result validated",
            extra={
                "event": "developer_worker.result.validated",
                "tenant_id": str(tenant_id),
                "workspace_id": str(workspace_id),
                "agent_definition_id": str(definition.id),
                "agent_version": definition.version,
                "agent_run_id": str(response.agent_run_id),
                "change_count": len(result.changes),
                "result_status": result.status.value,
                "challenge_level": result.challenge.level.value,
            },
        )
    return DeveloperWorkerExecutionResponse(
        agent_run_id=response.agent_run_id,
        agent_definition_id=response.agent_definition_id,
        agent_definition_version=response.agent_definition_version,
        status=response.status,
        selected_model=response.selected_model,
        model_run_id=response.model_run_id,
        result=result,
        error_code=response.error_code,
    )
