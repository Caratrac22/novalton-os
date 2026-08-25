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
