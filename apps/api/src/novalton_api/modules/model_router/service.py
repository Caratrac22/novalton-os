"""Pure eligibility/ranking over canonical provider routing targets."""

import logging
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.context import get_correlation_id
from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.contracts import (
    ContractEnforcementGrade,
    ExecutionTargetClass,
    GovernedProviderQualification,
    ProviderManagedRoute,
)
from novalton_api.modules.model_catalog import repository
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_router.schemas import (
    CostPolicy,
    EstimatedCost,
    ModelCapability,
    RoutableTargetKind,
    RoutingOutcome,
    RoutingReason,
    RoutingRequest,
    RoutingSimulationResult,
    SelectedCatalogModel,
)
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id

logger = logging.getLogger(__name__)
_MILLION = Decimal(1_000_000)
_RoutableTarget = ModelDefinition | ProviderManagedRoute


@dataclass(frozen=True)
class _Candidate:
    model: _RoutableTarget
    estimated_cost: Decimal | None
    qualification: GovernedProviderQualification | None = None


@dataclass(frozen=True)
class _CanonicalTargets:
    """One authoritative routing target per provider/model identity."""

    targets: tuple[_RoutableTarget, ...]
    raw_representation_count: int
    duplicate_identity_count: int
    provider_managed_precedence_count: int


def _canonicalize_targets(
    catalog_models: list[ModelDefinition], virtual_routes: tuple[ProviderManagedRoute, ...]
) -> _CanonicalTargets:
    """Deduplicate provider-neutral identities before any routing decision.

    Provider-managed routes are trusted declarations of dynamic routing semantics, so they
    deliberately replace a catalog representation with the same identity. Catalog metadata is
    never merged into the route: a concrete backend must not expand route guarantees.
    """
    representations: tuple[_RoutableTarget, ...] = (*catalog_models, *virtual_routes)
    targets_by_identity: dict[tuple[str, str], _RoutableTarget] = {}
    representation_counts: dict[tuple[str, str], int] = {}
    provider_managed_precedence_count = 0
    for target in representations:
        identity = (target.provider_id, target.provider_model_id)
        representation_counts[identity] = representation_counts.get(identity, 0) + 1
        existing = targets_by_identity.get(identity)
        if existing is None:
            targets_by_identity[identity] = target
        elif isinstance(target, ProviderManagedRoute) and not isinstance(
            existing, ProviderManagedRoute
        ):
            targets_by_identity[identity] = target
            provider_managed_precedence_count += 1
        elif isinstance(existing, ProviderManagedRoute) and not isinstance(
            target, ProviderManagedRoute
        ):
            provider_managed_precedence_count += 1
    return _CanonicalTargets(
        targets=tuple(
            identity_target[1] for identity_target in sorted(targets_by_identity.items())
        ),
        raw_representation_count=len(representations),
        duplicate_identity_count=sum(count > 1 for count in representation_counts.values()),
        provider_managed_precedence_count=provider_managed_precedence_count,
    )


def _requirements(data: RoutingRequest) -> frozenset[ModelCapability]:
    required = set(data.required_capabilities)
    if data.tool_calling_required:
        required.add(ModelCapability.TOOL_CALLING)
    if data.structured_output_required:
        required.add(ModelCapability.STRUCTURED_OUTPUT)
    if data.vision_required:
        required.add(ModelCapability.VISION)
    return frozenset(required)


def _cost(model: _RoutableTarget, data: RoutingRequest) -> Decimal | None:
    if (
        not isinstance(model, ModelDefinition)
        or model.input_price_per_million is None
        or model.currency is None
    ):
        return None
    total = Decimal(data.context_tokens_estimate) * model.input_price_per_million
    if data.expected_output_tokens is not None:
        if model.output_price_per_million is None:
            return None
        total += Decimal(data.expected_output_tokens) * model.output_price_per_million
    return total / _MILLION


def _capabilities_satisfied(model: _RoutableTarget, required: frozenset[ModelCapability]) -> bool:
    if isinstance(model, ProviderManagedRoute):
        return all(capability.value in model.capabilities for capability in required)
    return all(getattr(model, capability.value) is True for capability in required)


def _enforcement_grade(
    model: _RoutableTarget, qualification: GovernedProviderQualification | None = None
) -> ContractEnforcementGrade:
    if qualification is not None and isinstance(model, ModelDefinition):
        return qualification.contract_enforcement_grade
    if isinstance(model, ProviderManagedRoute):
        return model.contract_enforcement_grade
    return ContractEnforcementGrade(model.contract_enforcement_grade)


def _structured_output_capability(model: _RoutableTarget) -> bool:
    return (
        "structured_output" in model.capabilities
        if isinstance(model, ProviderManagedRoute)
        else model.structured_output is True
    )


def _active_qualification(
    model: _RoutableTarget,
    qualifications: dict[tuple[str, str], GovernedProviderQualification],
) -> GovernedProviderQualification | None:
    """Apply explicit overlays only to catalog identities, never dynamic provider routes."""
    if isinstance(model, ProviderManagedRoute):
        return None
    qualification = qualifications.get((model.provider_id, model.provider_model_id))
    return qualification if qualification is not None and qualification.enabled else None


def _rank_key(candidate: _Candidate, data: RoutingRequest) -> tuple[object, ...]:
    model = candidate.model
    free_rank = (
        0 if model.free_allowlisted else 1 if data.cost_policy == CostPolicy.PREFER_FREE else 0
    )
    known_price_rank = 0 if candidate.estimated_cost is not None else 1
    price = candidate.estimated_cost if candidate.estimated_cost is not None else Decimal(0)
    provider_preference_rank = 0 if model.provider_id == data.preferred_provider else 1
    return (
        free_rank,
        known_price_rank,
        price,
        provider_preference_rank,
        model.provider_id,
        model.provider_model_id,
        str(getattr(model, "id", model.provider_model_id)),
    )


def _ranking_reasons(
    selected: _Candidate, eligible: list[_Candidate], data: RoutingRequest
) -> list[RoutingReason]:
    reasons: list[RoutingReason] = []
    if data.cost_policy == CostPolicy.PREFER_FREE and selected.model.free_allowlisted:
        reasons.append(RoutingReason.FREE_ALLOWLIST_PREFERRED)
    elif data.cost_policy == CostPolicy.FREE_ONLY:
        reasons.append(RoutingReason.FREE_ONLY_SATISFIED)
    if selected.estimated_cost is None:
        reasons.append(RoutingReason.PRICING_UNKNOWN_DETERMINISTIC_SELECTION)
    else:
        reasons.append(RoutingReason.LOWEST_KNOWN_ESTIMATED_COST)

    selected_key = _rank_key(selected, data)
    cost_peers = [
        candidate for candidate in eligible if _rank_key(candidate, data)[:3] == selected_key[:3]
    ]
    if (
        data.preferred_provider is not None
        and selected.model.provider_id == data.preferred_provider
        and any(candidate.model.provider_id != data.preferred_provider for candidate in cost_peers)
    ):
        reasons.append(RoutingReason.PROVIDER_PREFERENCE_APPLIED)
    identity_peers = [
        candidate for candidate in cost_peers if _rank_key(candidate, data)[:4] == selected_key[:4]
    ]
    if len(identity_peers) > 1:
        reasons.append(RoutingReason.DETERMINISTIC_ID_TIE_BREAK)
    return reasons


def _no_suitable_reasons(
    *,
    available: int,
    context_rejected: int,
    capability_rejected: int,
    enforcement_rejected: int,
    free_rejected: int,
) -> list[RoutingReason]:
    if available == 0:
        return [RoutingReason.NO_AVAILABLE_MODELS]
    reasons: list[RoutingReason] = []
    if context_rejected:
        reasons.append(RoutingReason.CONTEXT_UNSATISFIED)
    if capability_rejected:
        reasons.append(RoutingReason.CAPABILITY_UNSATISFIED)
    if enforcement_rejected:
        reasons.append(RoutingReason.CONTRACT_ENFORCEMENT_UNSATISFIED)
    if free_rejected:
        reasons.append(RoutingReason.FREE_ONLY_POOL_EMPTY)
    return reasons or [RoutingReason.CAPABILITY_UNSATISFIED]


async def simulate(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    data: RoutingRequest,
    virtual_routes: tuple[ProviderManagedRoute, ...] = (),
) -> RoutingSimulationResult:
    """Select only; never invoke providers or persist routing side effects."""
    started_at = perf_counter()
    result: RoutingSimulationResult | None = None
    if (
        await get_workspace_by_tenant_and_id(
            session, tenant_id=tenant_id, workspace_id=workspace_id
        )
        is None
    ):
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)

    canonical_targets = _canonicalize_targets(
        await repository.list_routing_candidates(session), virtual_routes
    )
    forced_pair = get_settings().model_router_force_model_pair
    qualifications = get_settings().governed_provider_qualifications_by_identity
    required = _requirements(data)
    available = context_rejected = capability_rejected = enforcement_rejected = free_rejected = 0
    eligible: list[_Candidate] = []
    for model in canonical_targets.targets:
        if forced_pair is not None and (model.provider_id, model.provider_model_id) != forced_pair:
            continue
        if isinstance(model, ModelDefinition) and model.status != "AVAILABLE":
            continue
        if isinstance(model, ProviderManagedRoute) and not model.enabled:
            continue
        available += 1
        if (isinstance(model, ModelDefinition) and model.context_window is None) or (
            model.context_window is not None and model.context_window < data.context_tokens_estimate
        ):
            context_rejected += 1
            continue
        if not _capabilities_satisfied(model, required):
            capability_rejected += 1
            continue
        qualification = _active_qualification(model, qualifications)
        if not _enforcement_grade(model, qualification).satisfies(
            data.minimum_contract_enforcement_grade
        ):
            enforcement_rejected += 1
            continue
        if data.cost_policy == CostPolicy.FREE_ONLY and not model.free_allowlisted:
            free_rejected += 1
            continue
        eligible.append(
            _Candidate(model=model, estimated_cost=_cost(model, data), qualification=qualification)
        )

    if not eligible:
        result = RoutingSimulationResult(
            outcome=RoutingOutcome.NO_SUITABLE_MODEL,
            selected=None,
            reason_codes=_no_suitable_reasons(
                available=available,
                context_rejected=context_rejected,
                capability_rejected=capability_rejected,
                enforcement_rejected=enforcement_rejected,
                free_rejected=free_rejected,
            ),
            eligible_candidate_count=0,
            minimum_contract_enforcement_grade=data.minimum_contract_enforcement_grade,
        )
    else:
        preferred = (
            next(
                (
                    candidate
                    for candidate in eligible
                    if getattr(candidate.model, "id", None) == data.preferred_model_id
                ),
                None,
            )
            if data.preferred_model_id is not None
            else None
        )
        if preferred is not None:
            selected = preferred
            reasons = [RoutingReason.PREFERRED_MODEL_ACCEPTED]
        else:
            selected = min(eligible, key=lambda candidate: _rank_key(candidate, data))
            reasons = []
            if data.preferred_model_id is not None:
                reasons.append(RoutingReason.PREFERRED_MODEL_REJECTED)
            reasons.extend(_ranking_reasons(selected, eligible, data))
        reasons = [
            RoutingReason.AVAILABLE,
            RoutingReason.CAPABILITIES_SATISFIED,
            RoutingReason.CONTEXT_SATISFIED,
            *reasons,
        ]
        estimate = None
        if selected.estimated_cost is not None:
            estimate = EstimatedCost(
                amount=selected.estimated_cost,
                currency=selected.model.currency,
                input_tokens_estimate=data.context_tokens_estimate,
                output_tokens_estimate=data.expected_output_tokens,
            )
        result = RoutingSimulationResult(
            outcome=RoutingOutcome.SELECTED,
            selected=SelectedCatalogModel(
                catalog_model_id=getattr(selected.model, "id", None),
                provider_id=selected.model.provider_id,
                provider_model_id=selected.model.provider_model_id,
                display_name=selected.model.display_name,
                execution_target_class=ExecutionTargetClass(selected.model.execution_target_class),
                last_verified_at=getattr(selected.model, "last_verified_at", None),
                estimated_cost=estimate,
                target_kind=(
                    RoutableTargetKind.VIRTUAL_ROUTE
                    if isinstance(selected.model, ProviderManagedRoute)
                    else RoutableTargetKind.CATALOG_MODEL
                ),
                route_source=getattr(selected.model, "source", None),
                capability_declaration_source=getattr(selected.model, "capability_source", None),
                capability_policy=getattr(selected.model, "capability_policy", None),
                structured_output_capability=_structured_output_capability(selected.model),
                contract_enforcement_grade=_enforcement_grade(
                    selected.model, selected.qualification
                ),
                minimum_contract_enforcement_grade=data.minimum_contract_enforcement_grade,
                enforcement_metadata_source=(
                    selected.qualification.qualification_source.value
                    if selected.qualification is not None
                    else getattr(selected.model, "enforcement_metadata_source", None)
                ),
                qualification_present=selected.qualification is not None,
                qualification_source=(
                    selected.qualification.qualification_source
                    if selected.qualification is not None
                    else None
                ),
                upstream_provider_constraint=(
                    selected.qualification.upstream_provider
                    if selected.qualification is not None
                    else None
                ),
                provider_allow_fallbacks=(False if selected.qualification is not None else None),
                provider_require_parameters=selected.qualification is not None,
                declared_capabilities=(
                    selected.model.capabilities
                    if isinstance(selected.model, ProviderManagedRoute)
                    else frozenset(
                        capability.value
                        for capability in ModelCapability
                        if getattr(selected.model, capability.value) is True
                    )
                ),
                context_window=selected.model.context_window,
                max_output_tokens=selected.model.max_output_tokens,
                dynamic_resolution=getattr(selected.model, "dynamic_resolution", False),
            ),
            reason_codes=reasons,
            eligible_candidate_count=len(eligible),
            minimum_contract_enforcement_grade=data.minimum_contract_enforcement_grade,
        )

    logger.info(
        "Model routing simulation completed",
        extra={
            "event": "model_router.simulation.completed",
            "provider_id": result.selected.provider_id if result.selected else None,
            "model_id": str(result.selected.catalog_model_id) if result.selected else None,
            "provider_model_id": result.selected.provider_model_id if result.selected else None,
            "target_kind": result.selected.target_kind if result.selected else None,
            "route_source": result.selected.route_source if result.selected else None,
            "capability_policy": result.selected.capability_policy if result.selected else None,
            "contract_enforcement_grade": (
                result.selected.contract_enforcement_grade if result.selected else None
            ),
            "minimum_contract_enforcement_grade": (result.minimum_contract_enforcement_grade),
            "qualification_present": (
                result.selected.qualification_present if result.selected else False
            ),
            "qualification_source": (
                result.selected.qualification_source.value
                if result.selected and result.selected.qualification_source is not None
                else None
            ),
            "upstream_provider_constraint": (
                result.selected.upstream_provider_constraint if result.selected else None
            ),
            "provider_allow_fallbacks": (
                result.selected.provider_allow_fallbacks if result.selected else None
            ),
            "provider_require_parameters": (
                result.selected.provider_require_parameters if result.selected else False
            ),
            "dynamic_resolution": result.selected.dynamic_resolution if result.selected else None,
            "raw_representation_count": canonical_targets.raw_representation_count,
            "canonical_target_count": len(canonical_targets.targets),
            "duplicate_identity_count": canonical_targets.duplicate_identity_count,
            "canonical_precedence": (
                "provider_managed_route"
                if canonical_targets.provider_managed_precedence_count
                else "none"
            ),
            "candidate_count": result.eligible_candidate_count,
            "result_codes": [reason.value for reason in result.reason_codes],
            "correlation_id": get_correlation_id(),
            "duration_ms": round((perf_counter() - started_at) * 1000, 2),
        },
    )
    return result
