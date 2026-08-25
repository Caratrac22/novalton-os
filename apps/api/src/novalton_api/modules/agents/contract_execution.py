"""Provider-neutral contract compilation and generation strategy selection."""

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

MAX_SEMANTIC_CONSTRAINTS = 16
MAX_CONSTRAINT_TEXT = 240


class ContractStrategyTier(StrEnum):
    STRICT_SCHEMA = "STRICT_SCHEMA"
    JSON_OBJECT = "JSON_OBJECT"
    JSON_INSTRUCTION = "JSON_INSTRUCTION"


@dataclass(frozen=True)
class SemanticConstraint:
    code: str
    path: str
    instruction: str


@dataclass(frozen=True)
class ContractExecutionProfile:
    name: str
    json_schema: dict[str, Any]
    semantic_constraints: tuple[SemanticConstraint, ...]
    fingerprint: str

    @property
    def semantic_guidance(self) -> str:
        if not self.semantic_constraints:
            return ""
        lines = ["Semantic constraints that remain authoritative during local validation:"]
        for constraint in self.semantic_constraints:
            lines.append(f"- {constraint.code} at {constraint.path}: {constraint.instruction}")
        return "\n".join(lines)


@dataclass(frozen=True)
class ContractGenerationCapabilities:
    native_structured_output: bool
    json_object_output: bool = False
    provider_require_parameters: bool = False
    response_healing: bool = False


@dataclass(frozen=True)
class ContractGenerationStrategy:
    tier: ContractStrategyTier
    native_structured_output: bool
    json_object_output: bool
    require_parameters: bool
    response_healing: bool


def compile_contract(contract: type[BaseModel]) -> ContractExecutionProfile:
    schema = contract.model_json_schema()
    constraints = tuple(_semantic_constraints(contract))
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "name": contract.__name__,
                "schema": schema,
                "semantic_constraints": [constraint.__dict__ for constraint in constraints],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    return ContractExecutionProfile(
        name=contract.__name__,
        json_schema=schema,
        semantic_constraints=constraints,
        fingerprint=fingerprint,
    )


def select_generation_strategy(
    capabilities: ContractGenerationCapabilities,
    *,
    native_structured_output_required: bool,
) -> ContractGenerationStrategy | None:
    if capabilities.native_structured_output:
        return ContractGenerationStrategy(
            tier=ContractStrategyTier.STRICT_SCHEMA,
            native_structured_output=True,
            json_object_output=False,
            require_parameters=capabilities.provider_require_parameters,
            response_healing=capabilities.response_healing,
        )
    if native_structured_output_required:
        return None
    if capabilities.json_object_output:
        return ContractGenerationStrategy(
            tier=ContractStrategyTier.JSON_OBJECT,
            native_structured_output=False,
            json_object_output=True,
            require_parameters=capabilities.provider_require_parameters,
            response_healing=capabilities.response_healing,
        )
    return ContractGenerationStrategy(
        tier=ContractStrategyTier.JSON_INSTRUCTION,
        native_structured_output=False,
        json_object_output=False,
        require_parameters=capabilities.provider_require_parameters,
        response_healing=capabilities.response_healing,
    )


def _semantic_constraints(contract: type[BaseModel]) -> list[SemanticConstraint]:
    raw = getattr(contract, "semantic_constraints", ())
    constraints: list[SemanticConstraint] = []
    for item in raw[:MAX_SEMANTIC_CONSTRAINTS]:
        constraint = item if isinstance(item, SemanticConstraint) else SemanticConstraint(**item)
        constraints.append(
            SemanticConstraint(
                code=constraint.code[:64],
                path=constraint.path[:160],
                instruction=constraint.instruction[:MAX_CONSTRAINT_TEXT],
            )
        )
    return constraints
