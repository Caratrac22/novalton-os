from uuid import UUID

import pytest
from pydantic import ValidationError

from novalton_api.modules.policy.evaluator import EvaluationRule, action_matches, evaluate_rules
from novalton_api.modules.policy.schemas import (
    PolicyEffect,
    PolicyEvaluationRequest,
    PolicyRuleCreate,
    RiskLevel,
)

TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")


def request(**changes: object) -> PolicyEvaluationRequest:
    values: dict[str, object] = {
        "tenant_id": TENANT_ID,
        "workspace_id": WORKSPACE_ID,
        "action": "repository.write",
    }
    values.update(changes)
    return PolicyEvaluationRequest.model_validate(values)


def rule(number: int, effect: object = "ALLOW", **changes: object) -> EvaluationRule:
    values: dict[str, object] = {
        "id": UUID(f"30000000-0000-0000-0000-{number:012d}"),
        "name": f"Rule {number}",
        "action_pattern": "repository.write",
        "effect": effect,
        "actor_type": None,
        "resource_type": None,
        "conditions": [],
    }
    values.update(changes)
    return EvaluationRule(**values)


@pytest.mark.parametrize(
    ("pattern", "action", "matches"),
    [
        ("repository.write", "repository.write", True),
        ("repository.write", "repository.write.force", False),
        ("repository.*", "repository.write", True),
        ("repository.*", "repository", False),
        ("*", "repository.write", True),
        ("repo*", "repository.write", False),
        ("repository.*", "repositoryx.write", False),
    ],
)
def test_action_matching_has_narrow_edge_semantics(
    pattern: str, action: str, matches: bool
) -> None:
    assert action_matches(pattern, action) is matches


@pytest.mark.parametrize("effect", list(PolicyEffect))
def test_effect_validation_accepts_only_canonical_values(effect: PolicyEffect) -> None:
    data = PolicyRuleCreate(
        tenant_id=TENANT_ID,
        name="Canonical",
        action_pattern="repository.write",
        effect=effect,
    )
    assert data.effect is effect


def test_effect_validation_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        PolicyRuleCreate.model_validate(
            {
                "tenant_id": str(TENANT_ID),
                "name": "Invalid",
                "action_pattern": "repository.write",
                "effect": "ASK",
            }
        )


def test_no_match_requires_confirmation_and_audit() -> None:
    result = evaluate_rules(request(), [])
    assert result.effect == PolicyEffect.REQUIRE_CONFIRMATION
    assert result.matched_rule_ids == []
    assert result.reasons == ["no_matching_rule:confirmation_required"]
    assert result.confirmation_required is True
    assert result.audit_required is True


def test_all_matches_are_reported_in_stable_order_and_strictest_wins() -> None:
    rules = [rule(3, "ALLOW_WITH_LOG"), rule(1, "ALLOW"), rule(2, "BLOCK")]
    result = evaluate_rules(request(), rules)
    assert result.effect == PolicyEffect.BLOCK
    assert result.matched_rule_ids == [rules[1].id, rules[2].id, rules[0].id]
    assert result.matched_rule_names == ["Rule 1", "Rule 2", "Rule 3"]
    assert result.confirmation_required is False
    assert result.audit_required is True
    assert all(
        str(rule_id) in reason
        for rule_id, reason in zip(result.matched_rule_ids, result.reasons, strict=True)
    )


@pytest.mark.parametrize(
    ("strict", "loose", "expected"),
    [
        ("BLOCK", "ALLOW", PolicyEffect.BLOCK),
        ("BLOCK", "ALLOW_WITH_LOG", PolicyEffect.BLOCK),
        ("REQUIRE_CONFIRMATION", "ALLOW", PolicyEffect.REQUIRE_CONFIRMATION),
        ("REQUIRE_CONFIRMATION", "ALLOW_WITH_LOG", PolicyEffect.REQUIRE_CONFIRMATION),
    ],
)
def test_less_restrictive_rules_never_downgrade_strict_matches(
    strict: str, loose: str, expected: PolicyEffect
) -> None:
    assert evaluate_rules(request(), [rule(1, strict), rule(2, loose)]).effect == expected


def test_actor_resource_and_typed_conditions_must_all_match() -> None:
    constrained = rule(
        1,
        "ALLOW_WITH_LOG",
        actor_type="agent",
        resource_type="repository",
        conditions=[
            {"field": "risk_level", "operator": "in", "value": ["LOW", "MEDIUM"]},
            {"field": "environment", "operator": "equals", "value": "development"},
            {"field": "reversible", "operator": "equals", "value": True},
        ],
    )
    matching = request(
        actor_type="agent",
        resource_type="repository",
        resource_id=UUID("40000000-0000-0000-0000-000000000001"),
        context={
            "risk_level": RiskLevel.LOW,
            "environment": "development",
            "reversible": True,
        },
    )
    assert evaluate_rules(matching, [constrained]).effect == PolicyEffect.ALLOW_WITH_LOG
    mismatch = evaluate_rules(matching.model_copy(update={"actor_type": "service"}), [constrained])
    assert mismatch.matched_rule_ids == []


@pytest.mark.parametrize(
    "changes",
    [
        {"effect": "BROKEN"},
        {"action_pattern": "repository.**"},
        {"actor_type": "Agent Admin"},
        {"conditions": [{"field": "cost", "operator": "eval", "value": "x"}]},
        {"conditions": {"python": "__import__('os')"}},
    ],
)
def test_invalid_or_corrupt_rule_fails_closed(changes: dict[str, object]) -> None:
    result = evaluate_rules(request(), [rule(1, **changes)])
    assert result.effect == PolicyEffect.BLOCK
    assert result.matched_rule_ids == [rule(1).id]
    assert result.matched_rule_names == []
    assert result.reasons == [f"rule:{rule(1).id}:invalid_fail_closed"]


def test_corrupt_rule_for_an_unrelated_valid_action_pattern_does_not_apply() -> None:
    corrupt = rule(1, effect="BROKEN", action_pattern="email.send")
    result = evaluate_rules(request(), [corrupt])
    assert result.effect == PolicyEffect.REQUIRE_CONFIRMATION
    assert result.matched_rule_ids == []


def test_allow_has_no_confirmation_or_audit_flag() -> None:
    result = evaluate_rules(request(), [rule(1)])
    assert result.effect == PolicyEffect.ALLOW
    assert result.confirmation_required is False
    assert result.audit_required is False
