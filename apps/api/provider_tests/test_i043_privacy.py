"""Provider-free proof that GitHub credentials never cross I-043 observables."""

import inspect
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from novalton_api import main as _app_main  # noqa: F401
from novalton_api.core.config import Settings
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.github_publications import service
from novalton_api.modules.github_publications.config import GitHubBinding
from novalton_api.modules.github_publications.http_adapter import GitHubHttpAdapter
from novalton_api.modules.github_publications.models import GitHubPublicationAction
from novalton_api.modules.github_publications.schemas import (
    GitHubPublicationActionResponse,
    GitHubPublicationCreate,
)

SECRET = "NOVALTON_SUPER_SECRET_TEST_TOKEN_9431"
ROOT = Path(__file__).parents[3]


def binding() -> GitHubBinding:
    return GitHubBinding(
        "github", "https://api.github.com", "owner", "repo", "main", "v1", "key", "/workspace"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, content=SECRET.encode()),
        httpx.Response(403, content=SECRET.encode()),
        httpx.Response(500, content=SECRET.encode()),
        httpx.Response(302, headers={"location": "https://evil.invalid/"}),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"owner": "malformed"}),
    ],
)
async def test_http_failure_surfaces_are_secret_free(response: httpx.Response) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return response

    adapter = GitHubHttpAdapter(
        binding(),
        SecretStr(SECRET),
        max_response_bytes=1024,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(Exception) as error:
            await adapter.repository_metadata()
        error_value = error.value
        observed = " ".join([str(error_value), repr(error_value), repr(error_value.args)])
        assert SECRET not in observed
        assert SECRET not in str(response.headers)
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_oversized_and_sha_errors_are_secret_free() -> None:
    async def oversized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1025)

    adapter = GitHubHttpAdapter(
        binding(),
        SecretStr(SECRET),
        max_response_bytes=1024,
        transport=httpx.MockTransport(oversized),
    )
    try:
        with pytest.raises(RuntimeError) as error:
            await adapter.repository_metadata()
        assert SECRET not in repr(error.value)
    finally:
        await adapter.aclose()


def test_logging_and_service_errors_have_no_credential_surface(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(Exception) as error:
        raise service._fail("repository_mismatch")
    assert SECRET not in str(error.value)
    assert SECRET not in repr(error.value)
    for record in caplog.records:
        assert SECRET not in record.getMessage()
        assert SECRET not in repr(record.args)
        assert SECRET not in repr(record.exc_text)


def test_public_schemas_and_persistence_columns_are_non_secret() -> None:
    forbidden = {
        "token",
        "credential",
        "authorization",
        "secret",
        "pat",
        "raw_request",
        "raw_response",
        "credential_hash",
        "credential_fingerprint",
    }
    schema_names = set(GitHubPublicationCreate.model_fields) | set(
        GitHubPublicationActionResponse.model_fields
    )
    assert not any(any(word in name.casefold() for word in forbidden) for name in schema_names)
    column_names = {column.name.casefold() for column in GitHubPublicationAction.__table__.columns}
    assert not any(any(word in name for word in forbidden) for name in column_names)
    serialized = GitHubPublicationCreate(title="Title", body="Body").model_dump_json()
    assert SECRET not in serialized


def test_approval_audit_metadata_is_bounded_and_secret_free() -> None:
    data = AuditRecordCreate(
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        action="github.publication.create",
        actor_type="service",
        outcome="success",
        metadata={
            "approval_id": str(uuid4()),
            "status": "PUBLISHED",
            "failure_code": "repository_mismatch",
            "repository": "owner/repo",
            "branch": "novalton/action",
            "pr_number": 7,
        },
    )
    serialized = data.model_dump_json()
    assert SECRET not in serialized
    assert "authorization" not in serialized.casefold()
    assert "raw_response" not in serialized.casefold()


def test_fingerprint_code_is_token_independent() -> None:
    source = inspect.getsource(service.prepare)
    assert "resolve_github_credential" not in source
    assert "github_publication_pat" not in source
    assert '"binding": binding.version' in source
    assert '"key": binding.key' in source
    assert SECRET not in source


def test_settings_secretstr_is_redacted_everywhere() -> None:
    settings = Settings(github_publication_pat=SecretStr(SECRET))
    for representation in (
        str(settings),
        repr(settings),
        settings.model_dump_json(),
        repr(settings.model_dump()),
    ):
        assert SECRET not in representation
    assert str(settings.github_publication_pat) == "**********"


def test_frontend_projection_has_no_credential_or_raw_response_fields() -> None:
    component = (ROOT / "apps/web/src/components/github-publication.tsx").read_text()
    assert SECRET not in component
    assert "Authorization" not in component
    assert "credential" not in component.casefold()
    assert "raw response" not in component.casefold()
    assert "JSON.stringify(buildPublicationRequest(title, body))" in component


def test_no_credential_fingerprint_is_in_publication_implementation() -> None:
    source = "\n".join(
        path.read_text()
        for path in (ROOT / "apps/api/src/novalton_api/modules/github_publications").glob("*.py")
    )
    assert "sha256(token" not in source.casefold()
    assert "credential_fingerprint" not in source.casefold()
    assert "github_publication_pat" in source  # resolver boundary only; never fingerprint input
    assert "resolve_github_credential" not in inspect.getsource(service.prepare)
