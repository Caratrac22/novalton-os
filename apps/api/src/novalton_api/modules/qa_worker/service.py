"""Scoped QA Worker definition and I-022 execution integration."""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.modules.agents import execution, repository
from novalton_api.modules.agents.models import AgentDefinition
from novalton_api.modules.agents.schemas import AgentDefinitionStatus
from novalton_api.modules.qa_worker.contracts import QAWorkerResult
from novalton_api.modules.qa_worker.schemas import (
    QAWorkerValidationRequest,
    QAWorkerValidationResponse,
)

logger = logging.getLogger(__name__)
QA_WORKER_SLUG = "qa_worker"
QA_WORKER_NAME = "QA Worker"
QA_WORKER_CATEGORY = "quality"
QA_WORKER_MISSION = (
    "Evaluate one bounded software-development result against explicit acceptance criteria "
    "and return a validated QA assessment without executing tests or exercising authority."
)
QA_WORKER_CAPABILITIES = [
    "acceptance_validation",
    "defect_analysis",
    "quality_assurance",
    "regression_planning",
    "security_review_planning",
]
_CONTRACT_INSTRUCTIONS = (
    "Return a bounded QA assessment from supplied metadata only. Do not include or execute code, "
    "test scripts, commands, tools or function calls, credentials, URLs, provider/model overrides, "
    "approval flags, repository changes, fixes, worker chaining, or workflow mutations. A verdict "
    "is an assessment, never approval or authority. Recommended checks are concise prose only."
)


async def resolve_definition(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID
) -> AgentDefinition:
    definition = await repository.latest_definition(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        slug=QA_WORKER_SLUG,
    )
    if definition is None:
        raise ApplicationError("qa_worker_unavailable", "QA Worker is unavailable", status_code=404)
    if definition.status != AgentDefinitionStatus.ENABLED.value:
        raise ApplicationError("qa_worker_unavailable", "QA Worker is unavailable", status_code=409)
    return definition


async def validate(
    session: AsyncSession,
    *,
    registry: ProviderRegistry,
    tenant_id: UUID,
    workspace_id: UUID,
    data: QAWorkerValidationRequest,
) -> QAWorkerValidationResponse:
    definition = await resolve_definition(session, tenant_id=tenant_id, workspace_id=workspace_id)
    response = await execution.execute(
        session,
        registry=registry,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        definition_id=definition.id,
        data=data,
        result_contract=QAWorkerResult,
        contract_instructions=_CONTRACT_INSTRUCTIONS,
    )
    result = response.result
    if result is not None:
        assert isinstance(result, QAWorkerResult)
        logger.info(
            "QA Worker assessment validated",
            extra={
                "event": "qa_worker.assessment.validated",
                "tenant_id": str(tenant_id),
                "workspace_id": str(workspace_id),
                "agent_definition_id": str(definition.id),
                "agent_version": definition.version,
                "agent_run_id": str(response.agent_run_id),
                "verdict": result.verdict.value,
                "defect_count": len(result.defects),
                "result_status": result.status.value,
                "challenge_level": result.challenge.level.value,
            },
        )
    return QAWorkerValidationResponse(
        agent_run_id=response.agent_run_id,
        agent_definition_id=response.agent_definition_id,
        agent_definition_version=response.agent_definition_version,
        status=response.status,
        selected_model=response.selected_model,
        model_run_id=response.model_run_id,
        result=result,
        error_code=response.error_code,
    )
