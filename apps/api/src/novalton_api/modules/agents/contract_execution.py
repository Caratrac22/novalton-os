"""Provider-neutral contract compilation and generation strategy selection."""

import hashlib
import json
import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel

MAX_SEMANTIC_CONSTRAINTS = 16
MAX_CONSTRAINT_TEXT = 240
MAX_RESULT_SHAPE_CONSTRAINTS = 16
MAX_RESULT_SHAPE_PATH = 256
_CONSTRAINT_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PATH_PART = re.compile(r"(?:^|\.)([A-Za-z_][A-Za-z0-9_]*)|\[(\d+|\*)\]")


class ContractStrategyTier(StrEnum):
    STRICT_SCHEMA = "STRICT_SCHEMA"
    JSON_OBJECT = "JSON_OBJECT"
    JSON_INSTRUCTION = "JSON_INSTRUCTION"


@dataclass(frozen=True)
class SemanticConstraint:
    code: str
    path: str
    instruction: str


class ResultShapeConstraintKind(StrEnum):
    """Provider-neutral contextual restrictions on a validated result shape."""

    EXACT_ITEMS = "exact_items"
    MIN_ITEMS = "min_items"
    MAX_ITEMS = "max_items"
    EMPTY = "empty"
    ALLOWED_VALUES = "allowed_values"
    SEMANTIC = "semantic"


@dataclass(frozen=True)
class ResultShapeConstraint:
    """One bounded caller-supplied restriction layered over a base contract."""

    code: str
    path: str
    kind: ResultShapeConstraintKind
    value: int | tuple[str, ...] | None = None
    instruction: str = ""
    validator: Callable[[object], bool] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if isinstance(self.kind, str):
            object.__setattr__(self, "kind", ResultShapeConstraintKind(self.kind))
        if _CONSTRAINT_CODE.fullmatch(self.code) is None:
            raise ValueError("constraint code must be a normalized identifier")
        if not self.path or len(self.path) > MAX_RESULT_SHAPE_PATH:
            raise ValueError("constraint path is invalid")
        if self.kind in {
            ResultShapeConstraintKind.EXACT_ITEMS,
            ResultShapeConstraintKind.MIN_ITEMS,
            ResultShapeConstraintKind.MAX_ITEMS,
        } and (not isinstance(self.value, int) or self.value < 0):
            raise ValueError("item constraints require a non-negative integer value")
        if self.kind == ResultShapeConstraintKind.ALLOWED_VALUES and (
            not isinstance(self.value, tuple)
            or not self.value
            or len(self.value) > 16
            or any(not isinstance(item, str) or not item or len(item) > 128 for item in self.value)
        ):
            raise ValueError("allowed values must be a bounded non-empty tuple of strings")
        if self.kind == ResultShapeConstraintKind.SEMANTIC and self.validator is None:
            raise ValueError("semantic constraints require a local validator")
        if len(self.instruction) > MAX_CONSTRAINT_TEXT:
            raise ValueError("constraint instruction is too long")

    @classmethod
    def exact_items(cls, *, code: str, path: str, count: int) -> Self:
        return cls(code, path, ResultShapeConstraintKind.EXACT_ITEMS, count)

    @classmethod
    def min_items(cls, *, code: str, path: str, count: int) -> Self:
        return cls(code, path, ResultShapeConstraintKind.MIN_ITEMS, count)

    @classmethod
    def max_items(cls, *, code: str, path: str, count: int) -> Self:
        return cls(code, path, ResultShapeConstraintKind.MAX_ITEMS, count)

    @classmethod
    def empty(cls, *, code: str, path: str) -> Self:
        return cls(code, path, ResultShapeConstraintKind.EMPTY)

    @classmethod
    def allowed_values(cls, *, code: str, path: str, values: tuple[str, ...]) -> Self:
        return cls(code, path, ResultShapeConstraintKind.ALLOWED_VALUES, values)

    @classmethod
    def semantic(
        cls,
        *,
        code: str,
        path: str,
        instruction: str,
        validator: Callable[[object], bool],
    ) -> Self:
        return cls(
            code,
            path,
            ResultShapeConstraintKind.SEMANTIC,
            instruction=instruction,
            validator=validator,
        )

    def fingerprint_data(self) -> dict[str, object]:
        value: object = self.value
        if isinstance(value, tuple):
            value = list(value)
        return {
            "code": self.code,
            "path": self.path,
            "kind": self.kind.value,
            "value": value,
            "instruction": self.instruction,
        }


@dataclass(frozen=True)
class ContextualValidationFailure:
    """Safe contextual validation output containing no invalid provider values."""

    code: str
    path: str


def validate_result_shape(
    result: BaseModel, constraints: tuple[ResultShapeConstraint, ...]
) -> tuple[ContextualValidationFailure, ...]:
    """Validate contextual restrictions against the already base-validated result."""
    payload: object = result.model_dump(mode="json")
    failures: list[ContextualValidationFailure] = []
    for constraint in constraints[:MAX_RESULT_SHAPE_CONSTRAINTS]:
        values = _values_at_path(payload, constraint.path)
        if not values:
            failures.append(ContextualValidationFailure(constraint.code, constraint.path))
            continue
        for value in values:
            valid = _constraint_value_is_valid(constraint, value)
            if not valid:
                failures.append(ContextualValidationFailure(constraint.code, constraint.path))
                break
    return tuple(failures)


@dataclass(frozen=True)
class ContractExecutionProfile:
    name: str
    json_schema: dict[str, Any]
    semantic_constraints: tuple[SemanticConstraint, ...]
    result_shape_constraints: tuple[ResultShapeConstraint, ...]
    fingerprint: str

    @property
    def semantic_guidance(self) -> str:
        constraints = [
            SemanticConstraint(
                code=constraint.code,
                path=constraint.path,
                instruction=_constraint_instruction(constraint),
            )
            for constraint in self.result_shape_constraints
        ]
        all_constraints = (*self.semantic_constraints, *constraints)
        if not all_constraints:
            return ""
        lines = ["Semantic constraints that remain authoritative during local validation:"]
        for constraint in all_constraints:
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


def compile_contract(
    contract: type[BaseModel],
    *,
    result_shape_constraints: tuple[ResultShapeConstraint, ...] = (),
    contextual_constraints: tuple[ResultShapeConstraint, ...] | None = None,
) -> ContractExecutionProfile:
    if contextual_constraints is not None:
        if result_shape_constraints:
            raise ValueError("provide only one contextual constraint collection")
        result_shape_constraints = contextual_constraints
    schema = deepcopy(contract.model_json_schema())
    constraints = tuple(_semantic_constraints(contract))
    contextual = tuple(result_shape_constraints[:MAX_RESULT_SHAPE_CONSTRAINTS])
    for constraint in contextual:
        _apply_schema_constraint(schema, constraint)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "name": contract.__name__,
                "schema": schema,
                "semantic_constraints": [constraint.__dict__ for constraint in constraints],
                "result_shape_constraints": [
                    constraint.fingerprint_data() for constraint in contextual
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    return ContractExecutionProfile(
        name=contract.__name__,
        json_schema=schema,
        semantic_constraints=constraints,
        result_shape_constraints=contextual,
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


def _constraint_instruction(constraint: ResultShapeConstraint) -> str:
    if constraint.instruction:
        return constraint.instruction
    if constraint.kind == ResultShapeConstraintKind.EXACT_ITEMS:
        return f"The list must contain exactly {constraint.value} item(s)."
    if constraint.kind == ResultShapeConstraintKind.MIN_ITEMS:
        return f"The list must contain at least {constraint.value} item(s)."
    if constraint.kind in {ResultShapeConstraintKind.MAX_ITEMS, ResultShapeConstraintKind.EMPTY}:
        count = 0 if constraint.kind == ResultShapeConstraintKind.EMPTY else constraint.value
        return f"The list must contain at most {count} item(s)."
    if constraint.kind == ResultShapeConstraintKind.ALLOWED_VALUES:
        return "The field must contain one of the allowed values."
    return "The contextual semantic constraint must be satisfied."


def _tokenize_path(path: str) -> tuple[str | int, ...]:
    tokens: list[str | int] = []
    position = 0
    for match in _PATH_PART.finditer(path):
        if match.start() != position and not (position == 0 and match.start() == 0):
            raise ValueError("constraint path is invalid")
        tokens.append(match.group(1) or match.group(2))
        if match.group(2) is not None and match.group(2) != "*":
            tokens[-1] = int(tokens[-1])
        position = match.end()
    if position != len(path):
        raise ValueError("constraint path is invalid")
    return tuple(tokens)


def _values_at_path(payload: object, path: str) -> list[object]:
    values = [payload]
    for token in _tokenize_path(path):
        next_values: list[object] = []
        for value in values:
            is_mapping_value = isinstance(token, str) and isinstance(value, dict) and token in value
            is_list_value = (
                isinstance(token, int) and isinstance(value, list) and token < len(value)
            )
            if is_mapping_value or is_list_value:
                next_values.append(value[token])
            elif token == "*" and isinstance(value, list):
                next_values.extend(value)
        values = next_values
    return values


def _constraint_value_is_valid(constraint: ResultShapeConstraint, value: object) -> bool:
    if constraint.kind == ResultShapeConstraintKind.SEMANTIC:
        try:
            return bool(constraint.validator and constraint.validator(value))
        except Exception:
            return False
    if constraint.kind == ResultShapeConstraintKind.ALLOWED_VALUES:
        return value in constraint.value
    if not isinstance(value, list):
        return False
    size = len(value)
    if constraint.kind == ResultShapeConstraintKind.EXACT_ITEMS:
        return size == constraint.value
    if constraint.kind == ResultShapeConstraintKind.MIN_ITEMS:
        return size >= constraint.value
    if constraint.kind in {
        ResultShapeConstraintKind.MAX_ITEMS,
        ResultShapeConstraintKind.EMPTY,
    }:
        limit = 0 if constraint.kind == ResultShapeConstraintKind.EMPTY else constraint.value
        return size <= limit
    return False


def _apply_schema_constraint(schema: dict[str, Any], constraint: ResultShapeConstraint) -> None:
    nodes = _schema_nodes_at_path(schema, constraint.path)
    if not nodes:
        raise ValueError(
            f"constraint path is not representable in contract schema: {constraint.path}"
        )
    for node in nodes:
        if constraint.kind == ResultShapeConstraintKind.EXACT_ITEMS:
            node["minItems"] = constraint.value
            node["maxItems"] = constraint.value
        elif constraint.kind == ResultShapeConstraintKind.MIN_ITEMS:
            node["minItems"] = constraint.value
        elif constraint.kind in {
            ResultShapeConstraintKind.MAX_ITEMS,
            ResultShapeConstraintKind.EMPTY,
        }:
            node["maxItems"] = (
                0 if constraint.kind == ResultShapeConstraintKind.EMPTY else constraint.value
            )
        elif constraint.kind == ResultShapeConstraintKind.ALLOWED_VALUES:
            node["enum"] = list(constraint.value)


def _schema_nodes_at_path(schema: dict[str, Any], path: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = [schema]
    for token in _tokenize_path(path):
        next_nodes: list[dict[str, Any]] = []
        for node in nodes:
            node = _resolve_schema_node(node, schema)
            if isinstance(token, str) and token != "*":
                properties = node.get("properties", {})
                child = properties.get(token)
                if isinstance(child, dict):
                    next_nodes.append(_resolve_schema_node(child, schema))
            elif token == "*" or isinstance(token, int):
                child = node.get("items")
                if isinstance(child, dict):
                    next_nodes.append(_resolve_schema_node(child, schema))
        nodes = next_nodes
    return nodes


def _resolve_schema_node(node: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    reference = node.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
        return node
    definition = root.get("$defs", {}).get(reference.removeprefix("#/$defs/"))
    return definition if isinstance(definition, dict) else node


ContextualResultConstraint = ResultShapeConstraint
