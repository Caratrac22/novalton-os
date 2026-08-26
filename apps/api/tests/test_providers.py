import asyncio
import json
import logging
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from novalton_api.core.config import Settings, SettingsError
from novalton_api.core.context import reset_correlation_id, set_correlation_id
from novalton_api.core.logging import JsonFormatter
from novalton_api.infrastructure.providers import openai_compatible
from novalton_api.infrastructure.providers.base import ModelProvider
from novalton_api.infrastructure.providers.contracts import (
    MAX_MESSAGE_CHARACTERS,
    MAX_REQUEST_CHARACTERS,
    CatalogModel,
    ContractEnforcementGrade,
    GenerationRequest,
    GenerationResult,
    GovernedProviderQualification,
    JsonObjectRequest,
    Message,
    MessageRole,
    ProviderRequestOptions,
    QualificationSource,
    StructuredOutputRequest,
)
from novalton_api.infrastructure.providers.errors import (
    ProviderCancellationError,
    ProviderError,
    ProviderFailure,
    UnknownProviderError,
)
from novalton_api.infrastructure.providers.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
)
from novalton_api.infrastructure.providers.openrouter_catalog import OpenRouterCatalogSource
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.infrastructure.providers.urls import validate_provider_base_url

API_KEY = "sk-test-never-log-this-value"


def request(**changes: object) -> GenerationRequest:
    values: dict[str, object] = {
        "model_id": "vendor/model-1",
        "messages": [Message(role=MessageRole.USER, content="Bounded test prompt")],
        "max_output_tokens": 123,
    }
    values.update(changes)
    return GenerationRequest.model_validate(values)


def config(**changes: object) -> OpenAICompatibleConfig:
    values: dict[str, object] = {
        "provider_id": "openrouter",
        "base_url": "https://provider.example/v1",
        "api_key": SecretStr(API_KEY),
    }
    values.update(changes)
    return OpenAICompatibleConfig.model_validate(values)


def response_payload(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": "completion-id",
        "model": "vendor/model-actual",
        "choices": [
            {
                "message": {"role": "assistant", "content": "Normalized answer"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
    }
    values.update(changes)
    return values


def test_request_and_result_are_strict_bounded_and_serializable() -> None:
    generated = request()
    assert generated.provider_options is None
    assert generated.model_dump(mode="json", exclude_none=True) == {
        "model_id": "vendor/model-1",
        "messages": [{"role": "user", "content": "Bounded test prompt"}],
        "max_output_tokens": 123,
    }
    with pytest.raises(ValidationError):
        request(model_id="bad model")
    assert request(model_id="~openai/gpt-latest").model_id == "~openai/gpt-latest"
    with pytest.raises(ValidationError):
        request(model_id="openai/~gpt-latest")
    with pytest.raises(ValidationError):
        request(model_id="~~openai/gpt-latest")
    with pytest.raises(ValidationError):
        request(model_id="~")
    with pytest.raises(ValidationError):
        request(max_output_tokens=65_537)
    with pytest.raises(ValidationError):
        Message(role=MessageRole.USER, content="x" * (MAX_MESSAGE_CHARACTERS + 1))
    with pytest.raises(ValidationError, match="request limit"):
        request(
            messages=[
                Message(role=MessageRole.USER, content="x" * MAX_MESSAGE_CHARACTERS)
                for _ in range(MAX_REQUEST_CHARACTERS // MAX_MESSAGE_CHARACTERS + 1)
            ]
        )
    with pytest.raises(ValidationError):
        GenerationResult(
            provider_id="provider",
            model_id="model",
            content="answer",
            raw_response={"not": "allowed"},
        )
    with pytest.raises(ValidationError):
        GenerationResult(provider_id="~openrouter", model_id="model", content="answer")
    with pytest.raises(ValidationError):
        config(provider_id="~openrouter")


def test_structured_output_request_is_strict_bounded_and_serializable() -> None:
    structured = StructuredOutputRequest(
        name="AgentResult",
        json_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
    )

    assert request(structured_output=structured).model_dump(mode="json", exclude_none=True)[
        "structured_output"
    ] == {
        "name": "AgentResult",
        "json_schema": {
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
        "strict": True,
    }
    with pytest.raises(ValidationError):
        StructuredOutputRequest(name="bad name", json_schema={"type": "object"})
    with pytest.raises(ValidationError):
        StructuredOutputRequest(name="AgentResult", json_schema={})
    with pytest.raises(ValidationError):
        StructuredOutputRequest(
            name="AgentResult",
            json_schema={"type": "object"},
            provider_specific=True,
        )


def test_catalog_contract_is_strict_conservative_and_decimal() -> None:
    model = CatalogModel(
        provider_model_id="vendor/model-free",
        display_name="Model Free",
        input_price_per_million=Decimal("0"),
        output_price_per_million=Decimal("0.0000000001"),
        currency="USD",
    )
    assert model.reasoning is None
    assert model.coding is None
    assert model.tool_calling is None
    assert model.structured_output is None
    assert model.vision is None
    assert model.input_price_per_million == Decimal("0")
    with pytest.raises(ValidationError):
        CatalogModel(provider_model_id="bad model", display_name="Bad")
    with pytest.raises(ValidationError):
        CatalogModel(provider_model_id="model", display_name="Bad", context_window=0)
    with pytest.raises(ValidationError):
        CatalogModel(
            provider_model_id="model",
            display_name="Bad",
            input_price_per_million=Decimal("-1"),
            currency="USD",
        )


def test_governed_provider_qualifications_are_bounded_and_conservative() -> None:
    qualification = GovernedProviderQualification(
        provider_id="openrouter",
        provider_model_id="vendor/model",
        upstream_provider="openai",
        contract_enforcement_grade=ContractEnforcementGrade.PROVIDER_ENFORCED,
        qualification_source=QualificationSource.PROVIDER_DOCUMENTATION,
    )
    settings = Settings(governed_provider_qualifications=(qualification,))

    assert settings.governed_provider_qualifications_by_identity == {
        ("openrouter", "vendor/model"): qualification
    }
    assert qualification.contract_enforcement_grade == ContractEnforcementGrade.PROVIDER_ENFORCED
    with pytest.raises(ValidationError):
        Settings(
            governed_provider_qualifications=(
                qualification,
                qualification,
            )
        )
    with pytest.raises(ValidationError):
        GovernedProviderQualification(
            provider_id="openrouter",
            provider_model_id="vendor/model",
            upstream_provider="bad provider",
            contract_enforcement_grade=ContractEnforcementGrade.PROVIDER_ENFORCED,
            qualification_source=QualificationSource.OPERATOR_CONFIGURATION,
        )
    with pytest.raises(ValidationError):
        GovernedProviderQualification(
            provider_id="openrouter",
            provider_model_id="vendor/model",
            contract_enforcement_grade=ContractEnforcementGrade.BEST_EFFORT,
            qualification_source=QualificationSource.OPERATOR_CONFIGURATION,
        )
    with pytest.raises(ValidationError):
        CatalogModel(
            provider_model_id="model",
            display_name="Bad",
            input_price_per_million=Decimal("1"),
        )


@pytest.mark.asyncio
async def test_openrouter_catalog_normalizes_bounded_metadata_without_raw_payload() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.url == "https://provider.example/v1/models"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "vendor/model-free",
                        "name": "Vendor Model Free",
                        "context_length": 131072,
                        "top_provider": {"max_completion_tokens": 943718},
                        "supported_parameters": ["tools", "response_format"],
                        "architecture": {"input_modalities": ["text", "image"]},
                        "pricing": {"prompt": "0", "completion": "0.00000125"},
                        "raw_secret_metadata": "must-not-survive",
                    },
                    {"id": "~z-ai/glm-latest"},
                    {"id": "vendor/model-after-alias"},
                ]
            },
        )

    source = OpenRouterCatalogSource(config(), transport=httpx.MockTransport(handler))
    try:
        models = await source.list_models()
    finally:
        await source.aclose()
    assert len(captured) == 1
    assert captured[0].headers["accept"] == "application/json"
    assert captured[0].headers["accept-encoding"] == "identity"
    assert captured[0].headers["authorization"] == f"Bearer {API_KEY}"
    assert models == [
        CatalogModel(
            provider_model_id="vendor/model-free",
            display_name="Vendor Model Free",
            context_window=131072,
            max_output_tokens=943718,
            tool_calling=True,
            structured_output=True,
            vision=True,
            input_price_per_million=Decimal("0"),
            output_price_per_million=Decimal("1.25000000"),
            currency="USD",
        ),
        CatalogModel(provider_model_id="~z-ai/glm-latest", display_name="~z-ai/glm-latest"),
        CatalogModel(
            provider_model_id="vendor/model-after-alias",
            display_name="vendor/model-after-alias",
        ),
    ]
    assert "raw_secret_metadata" not in repr(models)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pricing", "input_price", "output_price", "currency"),
    [
        ({"prompt": "-1", "completion": "0.00000125"}, None, Decimal("1.25000000"), "USD"),
        ({"prompt": "0.0000005", "completion": "-1"}, Decimal("0.5000000"), None, "USD"),
        ({"prompt": "-1", "completion": "-1"}, None, None, None),
        (
            {"prompt": "0.0000005", "completion": "0.00000125"},
            Decimal("0.5000000"),
            Decimal("1.25000000"),
            "USD",
        ),
        ({"prompt": "0", "completion": "0"}, Decimal("0"), Decimal("0"), "USD"),
    ],
)
async def test_openrouter_catalog_normalizes_dynamic_pricing_sentinel(
    pricing: dict[str, object],
    input_price: Decimal | None,
    output_price: Decimal | None,
    currency: str | None,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"id": "vendor/model-pricing", "pricing": pricing}]},
        )

    source = OpenRouterCatalogSource(config(), transport=httpx.MockTransport(handler))
    try:
        models = await source.list_models()
    finally:
        await source.aclose()

    assert models[0].input_price_per_million == input_price
    assert models[0].output_price_per_million == output_price
    assert models[0].currency == currency


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "price",
    ["-0.5", "-2", "bad", "NaN", "Infinity", "-Infinity", None, 1, True, [], {}],
)
async def test_openrouter_catalog_rejects_invalid_pricing(price: object) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"id": "vendor/model-bad-price", "pricing": {"prompt": price}}]},
        )

    source = OpenRouterCatalogSource(config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as error:
            await source.list_models()
    finally:
        await source.aclose()

    assert error.value.failure == ProviderFailure.MALFORMED_RESPONSE


@pytest.mark.asyncio
async def test_openrouter_catalog_normalizes_live_auto_beta_dynamic_pricing() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "openrouter/auto-beta",
                        "name": "Auto Router (Beta)",
                        "pricing": {"prompt": "-1", "completion": "-1"},
                    }
                ]
            },
        )

    source = OpenRouterCatalogSource(config(), transport=httpx.MockTransport(handler))
    try:
        models = await source.list_models()
    finally:
        await source.aclose()

    assert models == [
        CatalogModel(
            provider_model_id="openrouter/auto-beta",
            display_name="Auto Router (Beta)",
            input_price_per_million=None,
            output_price_per_million=None,
            currency=None,
        )
    ]


@pytest.mark.asyncio
async def test_openrouter_generation_transport_headers_request_identity_encoding() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=response_payload())

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        await provider.complete(request())

    assert len(captured) == 1
    assert captured[0].headers["accept"] == "application/json"
    assert captured[0].headers["content-type"] == "application/json"
    assert captured[0].headers["authorization"] == f"Bearer {API_KEY}"
    assert captured[0].headers["accept-encoding"] == "identity"


@pytest.mark.asyncio
async def test_openai_compatible_execution_capabilities_are_explicit_and_independent() -> None:
    async with OpenAICompatibleProvider(
        config(require_parameters=True, response_healing=False),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response_payload())),
    ) as provider:
        assert provider.execution_capabilities.require_parameters is True
        assert provider.execution_capabilities.response_healing is False

    async with OpenAICompatibleProvider(
        config(),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response_payload())),
    ) as provider:
        assert provider.execution_capabilities.require_parameters is False
        assert provider.execution_capabilities.response_healing is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entries",
    [
        [{"id": "vendor/bad model"}],
        [{"id": "vendor/duplicate"}, {"id": "vendor/duplicate"}],
    ],
)
async def test_openrouter_catalog_rejects_malformed_or_duplicate_model_ids(
    entries: list[dict[str, str]],
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": entries})

    source = OpenRouterCatalogSource(config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as error:
            await source.list_models()
    finally:
        await source.aclose()
    assert error.value.failure == ProviderFailure.MALFORMED_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "failure"),
    [
        (401, ProviderFailure.AUTHENTICATION),
        (429, ProviderFailure.RATE_LIMIT),
        (504, ProviderFailure.TIMEOUT),
        (503, ProviderFailure.TRANSIENT),
    ],
)
async def test_openrouter_catalog_failures_are_sanitized(
    status: int, failure: ProviderFailure, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "raw-provider-secret"

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=secret)

    source = OpenRouterCatalogSource(config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as error:
            await source.list_models()
    finally:
        await source.aclose()
    assert error.value.failure == failure
    assert secret not in str(error.value)
    assert secret not in caplog.text
    assert API_KEY not in caplog.text


@pytest.mark.parametrize(
    "url",
    [
        "http://provider.example/v1",
        "https://user:password@provider.example/v1",
        "https://provider.example/v1?api_key=secret",
        "ftp://provider.example/v1",
    ],
)
def test_provider_url_rejects_unsafe_endpoints(url: str) -> None:
    with pytest.raises(ValueError, match="invalid provider base URL"):
        validate_provider_base_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://provider.example/v1/",
        "http://localhost:11434/v1",
        "http://127.0.0.1:8000/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_provider_url_accepts_https_and_explicit_loopback(url: str) -> None:
    assert validate_provider_base_url(url).endswith("/v1")


def test_secret_configuration_repr_and_environment_errors_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = config()
    assert API_KEY not in repr(configured)
    assert API_KEY not in repr(configured.model_dump())
    assert API_KEY not in repr(Settings(openai_compatible_api_key=SecretStr(API_KEY)))

    monkeypatch.setenv("NOVALTON_OPENAI_COMPATIBLE_API_KEY", API_KEY)
    monkeypatch.setenv("NOVALTON_PROVIDER_READ_TIMEOUT_SECONDS", "unbounded")
    with pytest.raises(SettingsError) as error:
        Settings.from_environment()
    assert API_KEY not in str(error.value)


@pytest.mark.asyncio
async def test_successful_normalization_serialization_and_nullable_usage() -> None:
    captured: list[httpx.Request] = []

    async def handler(http_request: httpx.Request) -> httpx.Response:
        captured.append(http_request)
        return httpx.Response(
            200,
            json=response_payload(usage=None),
            headers={"X-Request-ID": "safe-request_123"},
        )

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        assert isinstance(provider, ModelProvider)
        result = await provider.complete(request(model_id="~openai/gpt-latest"))

    assert result.model_dump(mode="json", exclude={"duration_ms"}) == {
        "provider_id": "openrouter",
        "model_id": "~openai/gpt-latest",
        "provider_resolved_model_id": "vendor/model-actual",
        "upstream_provider_id": None,
        "content": "Normalized answer",
        "finish_reason": "stop",
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "provider_request_id": "safe-request_123",
    }
    assert result.duration_ms is not None
    assert len(captured) == 1
    assert captured[0].url == "https://provider.example/v1/chat/completions"
    assert json.loads(captured[0].content) == {
        "model": "~openai/gpt-latest",
        "messages": [{"role": "user", "content": "Bounded test prompt"}],
        "stream": False,
        "max_tokens": 123,
    }
    assert captured[0].headers["authorization"] == f"Bearer {API_KEY}"


@pytest.mark.asyncio
async def test_openai_compatible_retains_fixed_requested_model_identity() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload(model="vendor/model-1"))

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        result = await provider.complete(request(model_id="vendor/model-1"))

    assert result.model_id == "vendor/model-1"
    assert result.provider_resolved_model_id == "vendor/model-1"


@pytest.mark.asyncio
async def test_openai_compatible_records_routed_alias_resolution_separately() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload(model="vendor/free-resolved"))

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        result = await provider.complete(request(model_id="openrouter/free"))

    assert result.model_id == "openrouter/free"
    assert result.provider_resolved_model_id == "vendor/free-resolved"


@pytest.mark.asyncio
async def test_structured_output_maps_to_openai_compatible_response_format() -> None:
    captured: list[httpx.Request] = []
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
        "additionalProperties": False,
    }

    async def handler(http_request: httpx.Request) -> httpx.Response:
        captured.append(http_request)
        return httpx.Response(200, json=response_payload())

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        await provider.complete(
            request(
                structured_output=StructuredOutputRequest(
                    name="AgentResult",
                    json_schema=schema,
                    strict=True,
                )
            )
        )

    assert json.loads(captured[0].content)["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "AgentResult",
            "schema": schema,
            "strict": True,
        },
    }


@pytest.mark.asyncio
async def test_provider_request_require_parameters_maps_to_openrouter_payload_metadata() -> None:
    captured: list[httpx.Request] = []

    async def handler(http_request: httpx.Request) -> httpx.Response:
        captured.append(http_request)
        return httpx.Response(200, json=response_payload())

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        await provider.complete(
            request(
                json_object=JsonObjectRequest(),
                provider_options=ProviderRequestOptions(
                    require_parameters=True,
                ),
            )
        )

    payload = json.loads(captured[0].content)
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["provider"] == {"require_parameters": True}
    assert "plugins" not in payload


@pytest.mark.asyncio
async def test_qualified_openrouter_request_pins_upstream_without_fallback() -> None:
    captured: list[httpx.Request] = []

    async def handler(http_request: httpx.Request) -> httpx.Response:
        captured.append(http_request)
        return httpx.Response(
            200,
            json=response_payload(
                openrouter_metadata={
                    "endpoints": {
                        "available": [
                            {
                                "provider": "OpenAI",
                                "model": "vendor/model-actual",
                                "selected": True,
                            }
                        ]
                    }
                }
            ),
        )

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        result = await provider.complete(
            request(
                provider_options=ProviderRequestOptions(
                    require_parameters=True,
                    upstream_provider="openai",
                    allow_fallbacks=False,
                )
            )
        )

    assert captured[0].headers["x-openrouter-metadata"] == "enabled"
    assert json.loads(captured[0].content)["provider"] == {
        "require_parameters": True,
        "only": ["openai"],
        "order": ["openai"],
        "allow_fallbacks": False,
    }
    assert result.provider_id == "openrouter"
    assert result.model_id == "vendor/model-1"
    assert result.provider_resolved_model_id == "vendor/model-actual"
    assert result.upstream_provider_id == "OpenAI"


@pytest.mark.asyncio
async def test_openrouter_unsafe_upstream_metadata_is_omitted_not_persisted() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=response_payload(
                openrouter_metadata={
                    "endpoints": {
                        "available": [{"provider": "Unsafe Provider Name", "selected": True}]
                    }
                }
            ),
        )

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        result = await provider.complete(request())

    assert result.upstream_provider_id is None


@pytest.mark.asyncio
async def test_pinned_openrouter_provider_failure_is_single_attempt_without_fallback() -> None:
    calls = 0

    async def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert json.loads(http_request.content)["provider"]["allow_fallbacks"] is False
        return httpx.Response(503, json={"error": {"message": "pinned upstream unavailable"}})

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        with pytest.raises(ProviderError) as error:
            await provider.complete(
                request(
                    provider_options=ProviderRequestOptions(
                        require_parameters=True,
                        upstream_provider="openai",
                        allow_fallbacks=False,
                    )
                )
            )

    assert error.value.failure == ProviderFailure.TRANSIENT
    assert calls == 1


@pytest.mark.asyncio
async def test_provider_request_response_healing_maps_to_openrouter_payload_plugin() -> None:
    captured: list[httpx.Request] = []

    async def handler(http_request: httpx.Request) -> httpx.Response:
        captured.append(http_request)
        return httpx.Response(200, json=response_payload())

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        await provider.complete(
            request(
                json_object=JsonObjectRequest(),
                provider_options=ProviderRequestOptions(
                    response_healing=True,
                ),
            )
        )

    payload = json.loads(captured[0].content)
    assert payload["response_format"] == {"type": "json_object"}
    assert "provider" not in payload
    assert payload["plugins"] == [{"id": "response-healing"}]


@pytest.mark.asyncio
async def test_usage_and_unsafe_request_id_normalization() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload(), headers={"X-Request-ID": "unsafe id"})

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        result = await provider.complete(request())
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (12, 4, 16)
    assert result.provider_request_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "failure"),
    [
        (401, b"not-json", ProviderFailure.AUTHENTICATION),
        (429, b"{}", ProviderFailure.RATE_LIMIT),
        (503, b"{}", ProviderFailure.TRANSIENT),
        (404, b"{}", ProviderFailure.INVALID_REQUEST),
        (400, b'{"error":{"code":"content_policy_violation"}}', ProviderFailure.REFUSAL),
    ],
)
async def test_http_failure_classification(
    status: int, body: bytes, failure: ProviderFailure
) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, content=body)

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        with pytest.raises(ProviderError) as error:
            await provider.complete(request())
    assert error.value.failure == failure
    assert calls == 1
    assert body.decode(errors="ignore") not in str(error.value)


@pytest.mark.asyncio
async def test_timeout_is_classified_without_retry() -> None:
    calls = 0

    async def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("provider secret body", request=http_request)

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        with pytest.raises(ProviderError) as error:
            await provider.complete(request())
    assert error.value.failure == ProviderFailure.TIMEOUT
    assert calls == 1
    assert "provider secret body" not in str(error.value)


@pytest.mark.asyncio
async def test_malformed_and_refusal_responses_are_classified() -> None:
    responses = iter(
        [
            httpx.Response(200, content=b"not-json"),
            httpx.Response(200, json=response_payload(choices=[])),
            httpx.Response(200, json=response_payload(model="bad model")),
            httpx.Response(
                200,
                json=response_payload(
                    choices=[
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "refusal": "private reason",
                            },
                            "finish_reason": "content_filter",
                        }
                    ]
                ),
            ),
        ]
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return next(responses)

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        expected = [
            ProviderFailure.MALFORMED_RESPONSE,
            ProviderFailure.MALFORMED_RESPONSE,
            ProviderFailure.MALFORMED_RESPONSE,
            ProviderFailure.REFUSAL,
        ]
        for failure in expected:
            with pytest.raises(ProviderError) as error:
                await provider.complete(request())
            assert error.value.failure == failure
            assert "private reason" not in str(error.value)


@pytest.mark.asyncio
async def test_cloud_endpoint_without_key_is_configuration_failure_but_loopback_is_allowed() -> (
    None
):
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload())

    cloud = config(api_key=None)
    async with OpenAICompatibleProvider(cloud, transport=httpx.MockTransport(handler)) as provider:
        with pytest.raises(ProviderError) as error:
            await provider.complete(request())
    assert error.value.failure == ProviderFailure.AUTHENTICATION

    local = config(base_url="http://localhost:8000/v1", api_key=None)
    async with OpenAICompatibleProvider(local, transport=httpx.MockTransport(handler)) as provider:
        assert (await provider.complete(request())).content == "Normalized answer"


@pytest.mark.asyncio
async def test_cancellation_propagates() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    async with OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(handler)
    ) as provider:
        with pytest.raises(ProviderCancellationError) as error:
            await provider.complete(request())
    assert isinstance(error.value, asyncio.CancelledError)
    assert error.value.failure == ProviderFailure.CANCELLATION


@pytest.mark.asyncio
async def test_bounded_response_is_rejected() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1_025)

    limited = config(max_response_bytes=1_024)
    async with OpenAICompatibleProvider(
        limited, transport=httpx.MockTransport(handler)
    ) as provider:
        with pytest.raises(ProviderError) as error:
            await provider.complete(request())
    assert error.value.failure == ProviderFailure.MALFORMED_RESPONSE


def test_registry_is_exact_and_has_no_fallback() -> None:
    provider = OpenAICompatibleProvider(
        config(), transport=httpx.MockTransport(lambda _: httpx.Response(200))
    )
    registry = ProviderRegistry([provider])
    assert registry.get("openrouter") is provider
    with pytest.raises(UnknownProviderError) as error:
        registry.get("missing")
    assert error.value.provider_id == "registry"
    assert "missing" not in str(error.value)


@pytest.mark.asyncio
async def test_logs_contain_only_safe_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = "prompt-that-must-not-be-logged"
    response_text = "response-that-must-not-be-logged"

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=response_payload(
                choices=[{"message": {"content": response_text}, "finish_reason": "stop"}]
            ),
        )

    token = set_correlation_id("provider-correlation")
    logged: list[tuple[str, dict[str, object]]] = []

    def capture_log(message: str, *, extra: dict[str, object]) -> None:
        logged.append((message, extra))

    monkeypatch.setattr(openai_compatible.logger, "info", capture_log)
    try:
        async with OpenAICompatibleProvider(
            config(), transport=httpx.MockTransport(handler)
        ) as provider:
            await provider.complete(
                request(messages=[Message(role=MessageRole.USER, content=prompt)])
            )
        message, extra = next(
            item for item in logged if item[1].get("event") == "provider.request.completed"
        )
        record = logging.LogRecord(
            name="provider-test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )
        for key, value in extra.items():
            setattr(record, key, value)
        rendered = JsonFormatter().format(record)
    finally:
        reset_correlation_id(token)
    assert '"provider_id": "openrouter"' in rendered
    assert '"model_id": "vendor/model-1"' in rendered
    assert '"correlation_id": "provider-correlation"' in rendered
    for secret in (API_KEY, "Authorization", prompt, response_text):
        assert all(secret not in str(item) for item in logged)
        assert secret not in rendered
