import httpx
import pytest
from pydantic import SecretStr

from novalton_api.modules.github_publications.config import GitHubBinding
from novalton_api.modules.github_publications.http_adapter import GitHubHttpAdapter


def binding() -> GitHubBinding:
    return GitHubBinding(
        "github", "https://api.github.com", "owner", "repo", "main", "v1", "k", "/workspace"
    )


@pytest.mark.asyncio
async def test_adapter_uses_fixed_host_and_rejects_redirects() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://evil.invalid"})

    adapter = GitHubHttpAdapter(
        binding(), SecretStr("test-token"), transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(RuntimeError, match="github_request_failed"):
            await adapter.repository_metadata()
        assert seen[0].url == "https://api.github.com/repos/owner/repo"
        assert adapter._client.follow_redirects is False
        assert adapter._client._trust_env is False
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_adapter_rejects_oversized_response_without_secret_in_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1025)

    adapter = GitHubHttpAdapter(
        binding(),
        SecretStr("super-secret"),
        max_response_bytes=1024,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(RuntimeError, match="github_response_too_large") as error:
            await adapter.repository_metadata()
        assert "super-secret" not in str(error.value)
    finally:
        await adapter.aclose()
