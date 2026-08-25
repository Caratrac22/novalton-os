"""One bounded provider-backed Agent execution attempt for I-022."""

import asyncio
import json
import logging
from math import ceil
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.contracts import (
    GenerationRequest,
    JsonObjectRequest,
    Message,
    MessageRole,
    ProviderExecutionCapabilities,
    ProviderRequestOptions,
    StructuredOutputRequest,
)
from novalton_api.infrastructure.providers.errors import (
    ProviderCancellationError,
    ProviderError,
    ProviderFailure,
)
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.modules.agents import repository, service
from novalton_api.modules.agents.contract_execution import (
    ContractGenerationCapabilities,
    ContractGenerationStrategy,
    ContractStrategyTier,
    compile_contract,
    select_generation_strategy,
)
from novalton_api.modules.agents.contracts import AgentInput, AgentResult, AgentResultStatus
from novalton_api.modules.agents.models import AgentDefinition, AgentRun
from novalton_api.modules.agents.schemas import (
    AgentDefinitionStatus,
    AgentExecutionResponse,
    AgentRunCreate,
    AgentRunStatus,
    SelectedModelResponse,
)
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_router import service as router_service
from novalton_api.modules.model_router.schemas import (
    CostPolicy,
    ModelCapability,
    RoutingOutcome,
    RoutingRequest,
)
from novalton_api.modules.model_usage import service as usage_service
from novalton_api.modules.model_usage.schemas import ModelRunStart

logger = logging.getLogger(__name__)
_EXPECTED_OUTPUT_TOKENS = 4096
_CONTEXT_OVERHEAD_TOKENS = 1024
_MAX_DIAGNOSTIC_ITEMS = 8
_MAX_DIAGNOSTIC_PATH_PARTS = 8
_MAX_DIAGNOSTIC_TEXT = 80
_KNOWN_CAPABILITIES = {capability.value: capability for capability in ModelCapability}

_RESULT_TO_RUN: dict[AgentResultStatus, tuple[AgentRunStatus, str | None]] = {
    AgentResultStatus.COMPLETED: (AgentRunStatus.SUCCEEDED, None),
    AgentResultStatus.PARTIAL: (AgentRunStatus.SUCCEEDED, None),
    AgentResultStatus.BLOCKED: (AgentRunStatus.FAILED, "agent_result_blocked"),
    AgentResultStatus.NEEDS_INPUT: (AgentRunStatus.FAILED, "agent_result_needs_input"),
    AgentResultStatus.FAILED: (AgentRunStatus.FAILED, "agent_result_failed"),
    AgentResultStatus.CANCELLED: (AgentRunStatus.CANCELLED, None),
}


def map_result_status(status: AgentResultStatus) -> tuple[AgentRunStatus, str | None]:
    """Map the richer result status to the deliberately narrow I-020 lifecycle."""
    return _RESULT_TO_RUN[status]


def _bounded_validation_diagnostics(error: ValidationError) -> dict[str, object]:
    errors = error.errors(include_url=False, include_context=False, include_input=False)
    error_types: list[str] = []
    field_paths: list[str] = []
    for item in errors[:_MAX_DIAGNOSTIC_ITEMS]:
        error_type = str(item.get("type", "unknown"))[:_MAX_DIAGNOSTIC_TEXT]
        if error_type not in error_types:
            error_types.append(error_type)
        loc = item.get("loc", ())
        if isinstance(loc, tuple | list):
            parts = [str(part)[:_MAX_DIAGNOSTIC_TEXT] for part in loc[:_MAX_DIAGNOSTIC_PATH_PARTS]]
            path = ".".join(parts) if parts else "<root>"
        else:
            path = str(loc)[:_MAX_DIAGNOSTIC_TEXT]
        if path not in field_paths:
            field_paths.append(path)
    return {
        "validation_error_count": len(errors),
        "validation_error_types": error_types[:_MAX_DIAGNOSTIC_ITEMS],
        "validation_error_paths": field_paths[:_MAX_DIAGNOSTIC_ITEMS],
    }


def _scope_id(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        raise ApplicationError(
            "invalid_agent_scope", "Agent scope is invalid", status_code=422
        ) from None


def _native_structured_output_required(data: AgentInput) -> bool:
    return (
        data.model_requirements.structured_output_required
        if data.model_requirements is not None
        else False
    )


def _routing_request(definition: AgentDefinition, data: AgentInput) -> RoutingRequest:
    hints = data.model_requirements
    names = set(definition.capabilities)
    if hints is not None:
        names.update(hints.required_capabilities)
    required = sorted(
        (_KNOWN_CAPABILITIES[name] for name in names if name in _KNOWN_CAPABILITIES),
        key=lambda capability: capability.value,
    )
    serialized_size = len(data.model_dump_json()) + len(definition.name) + len(definition.mission)
    context_estimate = max(1, ceil(serialized_size / 4) + _CONTEXT_OVERHEAD_TOKENS)
    if hints is not None and hints.minimum_context_tokens is not None:
        context_estimate = max(context_estimate, hints.minimum_context_tokens)
    return RoutingRequest(
        required_capabilities=required,
        context_tokens_estimate=context_estimate,
        tool_calling_required=hints.tool_calling_required if hints is not None else False,
        structured_output_required=_native_structured_output_required(data),
        vision_required=ModelCapability.VISION in required,
        expected_output_tokens=_EXPECTED_OUTPUT_TOKENS,
        cost_policy=CostPolicy.LOWEST_COST,
    )


def _generation_request(
    definition: AgentDefinition,
    data: AgentInput,
    *,
    provider_model_id: str,
    profile,
    strategy: ContractGenerationStrategy,
    contract_instructions: str | None = None,
    repair_diagnostics: dict[str, object] | None = None,
) -> GenerationRequest:
    result_schema = json.dumps(
        profile.json_schema,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    system = (
        f"You are the Novalton Agent '{definition.name}'. Mission: {definition.mission}\n"
        "Return exactly one JSON object and no surrounding text. It must satisfy the strict "
        f"{profile.name} JSON Schema: {result_schema}. "
        "Use only contract fields; requested_actions are proposals only. You have no tools, "
        "execution authority, hidden authority, or permission to approve actions. Do not reveal "
        "or invent hidden reasoning."
        + (
            " The provider may not enforce this schema; local strict validation remains "
            "authoritative."
            if strategy.tier != ContractStrategyTier.STRICT_SCHEMA
            else ""
        )
        + (f"\n{profile.semantic_guidance}" if profile.semantic_guidance else "")
        + (f" {contract_instructions}" if contract_instructions is not None else "")
    )
    user_payload: dict[str, object] = {"agent_input": data.model_dump(mode="json")}
    if repair_diagnostics is not None:
        user_payload["repair"] = {
            "instruction": "Return the entire corrected result JSON object, not a patch.",
            "validation_diagnostics": repair_diagnostics,
        }
    user = json.dumps(
        user_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    structured_output = None
    json_object = None
    if strategy.native_structured_output:
        structured_output = StructuredOutputRequest(
            name=profile.name,
            json_schema=profile.json_schema,
            strict=True,
        )
    elif strategy.json_object_output:
        json_object = JsonObjectRequest()
    provider_options = None
    if strategy.require_parameters or strategy.response_healing:
        provider_options = ProviderRequestOptions(
            require_parameters=strategy.require_parameters,
            response_healing=strategy.response_healing,
        )
    return GenerationRequest(
        model_id=provider_model_id,
        messages=[
            Message(role=MessageRole.SYSTEM, content=system),
            Message(role=MessageRole.USER, content=user),
        ],
        max_output_tokens=_EXPECTED_OUTPUT_TOKENS,
        structured_output=structured_output,
        json_object=json_object,
        provider_options=provider_options,
    )


def _response(
    run: AgentRun,
    *,
    definition: AgentDefinition,
    selected: SelectedModelResponse | None = None,
    model_run_id: UUID | None = None,
    result: AgentResult | None = None,
    error_code: str | None = None,
) -> AgentExecutionResponse:
    return AgentExecutionResponse(
        agent_run_id=run.id,
        agent_definition_id=definition.id,
        agent_definition_version=definition.version,
        status=AgentRunStatus(run.status),
        selected_model=selected,
        model_run_id=model_run_id,
        result=result,
        error_code=error_code,
    )


async def _fail_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    run_id: UUID,
    code: str,
) -> AgentRun:
    return await service.fail_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=run_id,
        failure_code=code,
    )


async def execute[AgentResultT: AgentResult](
    session: AsyncSession,
    *,
    registry: ProviderRegistry,
    tenant_id: UUID,
    workspace_id: UUID,
    definition_id: UUID,
    data: AgentInput,
    result_contract: type[AgentResultT] = AgentResult,
    contract_instructions: str | None = None,
) -> AgentExecutionResponse:
    """Execute one provider call without retries, fallback, tools, or content persistence."""
    profile = compile_contract(result_contract)
    definition = await service.get_definition(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        definition_id=definition_id,
    )
    if definition.status != AgentDefinitionStatus.ENABLED.value:
        raise ApplicationError(
            "agent_definition_unavailable", "Agent definition is unavailable", status_code=409
        )
    project_id = _scope_id(data.project_id)
    task_id = _scope_id(data.task_id)
    run = await service.create_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data=AgentRunCreate(
            agent_definition_id=definition.id,
            project_id=project_id,
            task_id=task_id,
        ),
    )
    run = await service.start_run(
        session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run.id
    )
    route = await router_service.simulate(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data=_routing_request(definition, data),
    )
    if route.outcome == RoutingOutcome.NO_SUITABLE_MODEL or route.selected is None:
        run = await _fail_agent(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run.id,
            code="no_suitable_model",
        )
        return _response(run, definition=definition, error_code="no_suitable_model")

    routed = route.selected
    selected = SelectedModelResponse(
        catalog_model_id=routed.catalog_model_id,
        provider_id=routed.provider_id,
        provider_model_id=routed.provider_model_id,
    )
    estimate = routed.estimated_cost
    model_run = await usage_service.start_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data=ModelRunStart(
            model_definition_id=routed.catalog_model_id,
            agent_run_id=run.id,
            project_id=project_id,
            estimated_cost=estimate.amount if estimate is not None else None,
            currency=estimate.currency if estimate is not None else None,
        ),
    )
    linked = await repository.link_model_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=run.id,
        model_run_id=model_run.id,
    )
    if linked is None:
        await usage_service.mark_failed(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            model_run_id=model_run.id,
            failure=ProviderFailure.INVALID_REQUEST,
        )
        run = await _fail_agent(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run.id,
            code="agent_lifecycle_conflict",
        )
        return _response(
            run,
            definition=definition,
            selected=selected,
            model_run_id=model_run.id,
            error_code="agent_lifecycle_conflict",
        )
    await session.commit()
    run = linked

    identity_mismatch = False
    try:
        provider = registry.get(routed.provider_id)
        if provider.provider_id != routed.provider_id:
            identity_mismatch = True
            raise ProviderError(ProviderFailure.INVALID_REQUEST, provider_id="registry")
        provider_capabilities = getattr(
            provider, "execution_capabilities", ProviderExecutionCapabilities()
        )
        model_definition = await session.get(ModelDefinition, routed.catalog_model_id)
        native_structured = bool(
            model_definition is not None and model_definition.structured_output is True
        )
        strategy = select_generation_strategy(
            ContractGenerationCapabilities(
                native_structured_output=native_structured,
                json_object_output=False,
                provider_require_parameters=provider_capabilities.require_parameters,
                response_healing=provider_capabilities.response_healing,
            ),
            native_structured_output_required=_native_structured_output_required(data),
        )
        if strategy is None:
            await usage_service.mark_failed(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                model_run_id=model_run.id,
                failure=ProviderFailure.INVALID_REQUEST,
            )
            run = await _fail_agent(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                run_id=run.id,
                code="native_structured_output_required",
            )
            return _response(
                run,
                definition=definition,
                selected=selected,
                model_run_id=model_run.id,
                error_code="native_structured_output_required",
            )
        logger.info(
            "Agent contract strategy selected",
            extra={
                "event": "agent.contract.strategy.selected",
                "agent_result_contract": profile.name,
                "contract_fingerprint": profile.fingerprint,
                "strategy_tier": strategy.tier.value,
                "native_structured_output": strategy.native_structured_output,
                "response_healing": strategy.response_healing,
                "agent_run_id": str(run.id),
                "model_run_id": str(model_run.id),
                "provider_id": routed.provider_id,
                "provider_model_id": routed.provider_model_id,
            },
        )
        generation = await provider.complete(
            _generation_request(
                definition,
                data,
                provider_model_id=routed.provider_model_id,
                profile=profile,
                strategy=strategy,
                contract_instructions=contract_instructions,
            )
        )
    except (ProviderCancellationError, asyncio.CancelledError):
        await usage_service.cancel_run(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            model_run_id=model_run.id,
        )
        await service.cancel_run(
            session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run.id
        )
        raise
    except ProviderError as error:
        if error.failure == ProviderFailure.CANCELLATION:
            await usage_service.cancel_run(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                model_run_id=model_run.id,
            )
            await service.cancel_run(
                session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run.id
            )
            raise ProviderCancellationError(provider_id=routed.provider_id) from None
        await usage_service.mark_failed(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            model_run_id=model_run.id,
            failure=error.failure,
        )
        code = (
            "provider_identity_mismatch" if identity_mismatch else f"provider_{error.failure.value}"
        )
        run = await _fail_agent(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run.id,
            code=code,
        )
        return _response(
            run,
            definition=definition,
            selected=selected,
            model_run_id=model_run.id,
            error_code=code,
        )
    except Exception:
        await usage_service.mark_failed(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            model_run_id=model_run.id,
            failure=ProviderFailure.UNKNOWN,
        )
        run = await _fail_agent(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run.id,
            code="provider_unknown_provider_error",
        )
        return _response(
            run,
            definition=definition,
            selected=selected,
            model_run_id=model_run.id,
            error_code="provider_unknown_provider_error",
        )

    if (generation.provider_id, generation.model_id) != (
        routed.provider_id,
        routed.provider_model_id,
    ):
        await usage_service.mark_failed(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            model_run_id=model_run.id,
            failure=ProviderFailure.INVALID_REQUEST,
        )
        run = await _fail_agent(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run.id,
            code="provider_identity_mismatch",
        )
        return _response(
            run,
            definition=definition,
            selected=selected,
            model_run_id=model_run.id,
            error_code="provider_identity_mismatch",
        )

    try:
        await usage_service.mark_succeeded(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            model_run_id=model_run.id,
            result=generation,
        )
    except ApplicationError:
        await usage_service.mark_failed(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            model_run_id=model_run.id,
            failure=ProviderFailure.MALFORMED_RESPONSE,
        )
        run = await _fail_agent(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run.id,
            code="invalid_provider_usage",
        )
        return _response(
            run,
            definition=definition,
            selected=selected,
            model_run_id=model_run.id,
            error_code="invalid_provider_usage",
        )
    try:
        json.loads(generation.content)
    except (json.JSONDecodeError, TypeError):
        run = await _fail_agent(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run.id,
            code="invalid_provider_json",
        )
        return _response(
            run,
            definition=definition,
            selected=selected,
            model_run_id=model_run.id,
            error_code="invalid_provider_json",
        )
    try:
        result = result_contract.model_validate_json(generation.content, strict=True)
    except ValidationError as error:
        diagnostics = _bounded_validation_diagnostics(error)
        logger.warning(
            "Strict agent result validation failed",
            extra={
                "event": "agent.contract.validation_failed",
                "agent_result_contract": profile.name,
                "contract_fingerprint": profile.fingerprint,
                "agent_run_id": str(run.id),
                "model_run_id": str(model_run.id),
                "provider_id": routed.provider_id,
                "provider_model_id": routed.provider_model_id,
                **diagnostics,
            },
        )
        if data.permitted_tools == []:
            repair_model_run = await usage_service.start_run(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                data=ModelRunStart(
                    model_definition_id=routed.catalog_model_id,
                    agent_run_id=run.id,
                    project_id=project_id,
                    estimated_cost=estimate.amount if estimate is not None else None,
                    currency=estimate.currency if estimate is not None else None,
                ),
            )
            logger.info(
                "Agent contract repair started",
                extra={
                    "event": "agent.contract.repair.started",
                    "agent_result_contract": profile.name,
                    "contract_fingerprint": profile.fingerprint,
                    "agent_run_id": str(run.id),
                    "model_run_id": str(repair_model_run.id),
                    "provider_id": routed.provider_id,
                    "provider_model_id": routed.provider_model_id,
                    "repair_attempt": 1,
                    **diagnostics,
                },
            )
            try:
                generation = await provider.complete(
                    _generation_request(
                        definition,
                        data,
                        provider_model_id=routed.provider_model_id,
                        profile=profile,
                        strategy=strategy,
                        contract_instructions=contract_instructions,
                        repair_diagnostics=diagnostics,
                    )
                )
                if (generation.provider_id, generation.model_id) != (
                    routed.provider_id,
                    routed.provider_model_id,
                ):
                    raise ProviderError(
                        ProviderFailure.INVALID_REQUEST, provider_id=routed.provider_id
                    )
            except ProviderCancellationError:
                await usage_service.cancel_run(
                    session,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    model_run_id=repair_model_run.id,
                )
                await service.cancel_run(
                    session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run.id
                )
                raise
            except ProviderError as error:
                await usage_service.mark_failed(
                    session,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    model_run_id=repair_model_run.id,
                    failure=error.failure,
                )
                logger.info(
                    "Agent contract repair completed",
                    extra={
                        "event": "agent.contract.repair.completed",
                        "agent_result_contract": profile.name,
                        "contract_fingerprint": profile.fingerprint,
                        "agent_run_id": str(run.id),
                        "model_run_id": str(repair_model_run.id),
                        "provider_id": routed.provider_id,
                        "provider_model_id": routed.provider_model_id,
                        "repair_attempt": 1,
                        "repair_succeeded": False,
                    },
                )
                result = None
            except Exception:
                await usage_service.mark_failed(
                    session,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    model_run_id=repair_model_run.id,
                    failure=ProviderFailure.UNKNOWN,
                )
                result = None
            else:
                try:
                    await usage_service.mark_succeeded(
                        session,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        model_run_id=repair_model_run.id,
                        result=generation,
                    )
                except ApplicationError:
                    await usage_service.mark_failed(
                        session,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        model_run_id=repair_model_run.id,
                        failure=ProviderFailure.MALFORMED_RESPONSE,
                    )
                    result = None
                else:
                    try:
                        json.loads(generation.content)
                        result = result_contract.model_validate_json(
                            generation.content, strict=True
                        )
                    except (json.JSONDecodeError, TypeError, ValidationError):
                        result = None
                    logger.info(
                        "Agent contract repair completed",
                        extra={
                            "event": "agent.contract.repair.completed",
                            "agent_result_contract": profile.name,
                            "contract_fingerprint": profile.fingerprint,
                            "agent_run_id": str(run.id),
                            "model_run_id": str(repair_model_run.id),
                            "provider_id": routed.provider_id,
                            "provider_model_id": routed.provider_model_id,
                            "repair_attempt": 1,
                            "repair_succeeded": result is not None,
                        },
                    )
        else:
            result = None
    if result is None:
        run = await _fail_agent(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run.id,
            code="invalid_agent_result",
        )
        return _response(
            run,
            definition=definition,
            selected=selected,
            model_run_id=model_run.id,
            error_code="invalid_agent_result",
        )

    terminal, failure_code = map_result_status(result.status)
    if terminal == AgentRunStatus.SUCCEEDED:
        run = await service.succeed_run(
            session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run.id
        )
    elif terminal == AgentRunStatus.CANCELLED:
        run = await service.cancel_run(
            session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run.id
        )
    else:
        run = await _fail_agent(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run.id,
            code=failure_code or "agent_result_failed",
        )
    logger.info(
        "Agent execution completed",
        extra={
            "event": (
                "agent.run.completed"
                if terminal == AgentRunStatus.SUCCEEDED
                else "agent.run.failed"
            ),
            "agent_definition_id": str(definition.id),
            "agent_run_id": str(run.id),
            "agent_version": definition.version,
            "model_run_id": str(model_run.id),
            "provider_id": routed.provider_id,
            "provider_model_id": routed.provider_model_id,
            "agent_result_status": result.status.value,
        },
    )
    return _response(
        run,
        definition=definition,
        selected=selected,
        model_run_id=model_run.id,
        result=result,
        error_code=failure_code,
    )
