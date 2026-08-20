"""Pure deterministic policy matching and restrictive combination."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from novalton_api.modules.policy.schemas import (
    ACTION_PATTERN,
    TYPE_IDENTIFIER,
    PolicyCondition,
    PolicyEffect,
    PolicyEvaluationRequest,
    PolicyEvaluationResult,
)

EFFECT_PRECEDENCE = {
    PolicyEffect.ALLOW: 0,
    PolicyEffect.ALLOW_WITH_LOG: 1,
    PolicyEffect.REQUIRE_CONFIRMATION: 2,
    PolicyEffect.BLOCK: 3,
}
NO_MATCH_EFFECT = PolicyEffect.REQUIRE_CONFIRMATION


@dataclass(frozen=True)
class EvaluationRule:
    id: UUID
    name: str
    action_pattern: str
    effect: object
    actor_type: str | None
    resource_type: str | None
    conditions: object


def action_matches(pattern: str, action: str) -> bool:
    """Match exact action names or one terminal namespace wildcard, without regex data."""
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        namespace = pattern[:-2]
        return action.startswith(f"{namespace}.")
    return pattern == action


def _condition_matches(condition: PolicyCondition, request: PolicyEvaluationRequest) -> bool:
    actual: Any = getattr(request.context, condition.field)
    if actual is None:
        return False
    if hasattr(actual, "value"):
        actual = actual.value
    if condition.operator == "equals":
        return actual == condition.value
    return actual in condition.value


def _invalid_rule_result(rule: EvaluationRule) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        effect=PolicyEffect.BLOCK,
        matched_rule_ids=[rule.id],
        matched_rule_names=[],
        reasons=[f"rule:{rule.id}:invalid_fail_closed"],
        confirmation_required=False,
        audit_required=True,
    )


def evaluate_rules(
    request: PolicyEvaluationRequest, rules: list[EvaluationRule]
) -> PolicyEvaluationResult:
    """Evaluate already scope-filtered rules; invalid records fail closed."""
    matches: list[tuple[EvaluationRule, PolicyEffect]] = []
    for rule in rules:
        try:
            if ACTION_PATTERN.fullmatch(rule.action_pattern) is None:
                raise ValueError("invalid action pattern")
            if not action_matches(rule.action_pattern, request.action):
                continue
            effect = PolicyEffect(rule.effect)
            if rule.actor_type is not None and TYPE_IDENTIFIER.fullmatch(rule.actor_type) is None:
                raise ValueError("invalid actor type")
            if (
                rule.resource_type is not None
                and TYPE_IDENTIFIER.fullmatch(rule.resource_type) is None
            ):
                raise ValueError("invalid resource type")
            conditions = [PolicyCondition.model_validate(item) for item in rule.conditions]
            if rule.actor_type is not None and rule.actor_type != request.actor_type:
                continue
            if rule.resource_type is not None and rule.resource_type != request.resource_type:
                continue
            if not all(_condition_matches(condition, request) for condition in conditions):
                continue
        except (TypeError, ValueError, ValidationError):
            return _invalid_rule_result(rule)
        matches.append((rule, effect))

    if not matches:
        return PolicyEvaluationResult(
            effect=NO_MATCH_EFFECT,
            matched_rule_ids=[],
            matched_rule_names=[],
            reasons=["no_matching_rule:confirmation_required"],
            confirmation_required=True,
            audit_required=True,
        )

    matches.sort(key=lambda item: (EFFECT_PRECEDENCE[item[1]], str(item[0].id)), reverse=True)
    final_effect = matches[0][1]
    ordered = sorted(matches, key=lambda item: str(item[0].id))
    return PolicyEvaluationResult(
        effect=final_effect,
        matched_rule_ids=[rule.id for rule, _ in ordered],
        matched_rule_names=[rule.name for rule, _ in ordered],
        reasons=[f"rule:{rule.id}:matched:{effect.value}" for rule, effect in ordered],
        confirmation_required=final_effect == PolicyEffect.REQUIRE_CONFIRMATION,
        audit_required=final_effect != PolicyEffect.ALLOW,
    )
