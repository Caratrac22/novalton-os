from novalton_api.modules.agents.output_budget import classify_truncation, select_output_budget


def test_output_budget_expands_once_but_never_exceeds_known_model_limit() -> None:
    initial = select_output_budget(
        expected_output_tokens=3000,
        known_model_maximum=6000,
        safety_ceiling=65_536,
    )
    recovery = select_output_budget(
        expected_output_tokens=3000,
        known_model_maximum=6000,
        safety_ceiling=65_536,
        recovery=True,
    )
    assert initial.tokens == 4500
    assert recovery.tokens == 6000
    assert recovery.source == "recovery_model_maximum"


def test_truncation_requires_explicit_token_limit_finish_reason() -> None:
    assert classify_truncation("length") == "TOKEN_LIMIT"
    assert classify_truncation("max_tokens") == "TOKEN_LIMIT"
    assert classify_truncation("stop") == "OTHER"
    assert classify_truncation(None) == "NONE"


def test_large_catalog_maximum_stays_bounded_by_execution_safety_ceiling() -> None:
    budget = select_output_budget(
        expected_output_tokens=3000,
        known_model_maximum=943718,
        safety_ceiling=65_536,
    )
    assert budget.tokens == 4500
    assert budget.tokens < 943718


def test_small_catalog_maximum_still_clamps_execution_budget() -> None:
    budget = select_output_budget(
        expected_output_tokens=3000,
        known_model_maximum=4096,
        safety_ceiling=65_536,
    )
    assert budget.tokens == 4096
