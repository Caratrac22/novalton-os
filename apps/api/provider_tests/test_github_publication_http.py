import hashlib
import json

import httpx
import pytest
from pydantic import SecretStr

from novalton_api.modules.github_publications.adapter import GitHubOperationalError
from novalton_api.modules.github_publications.config import GitHubBinding
from novalton_api.modules.github_publications.http_adapter import GitHubHttpAdapter


def make_adapter(handler, limit=1_048_576):
    binding = GitHubBinding(
        "github", "https://api.github.com", "owner", "repo", "main", "v1", "key", "/workspace"
    )
    return GitHubHttpAdapter(
        binding,
        SecretStr("distinctive-token"),
        max_response_bytes=limit,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_repository_metadata_returns_strict_typed_identity():
    async def handler(_request):
        return httpx.Response(
            200,
            json={
                "owner": {"login": "different-owner"},
                "name": "different-repo",
                "default_branch": "develop",
            },
        )

    adapter = make_adapter(handler)
    try:
        assert await adapter.repository_metadata() == {
            "provider": "github",
            "owner": "different-owner",
            "repository": "different-repo",
            "default_branch": "develop",
        }
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"owner": {"login": "owner"}, "name": "repo", "default_branch": None},
        {"owner": {"login": "owner"}, "name": "repo", "default_branch": 7},
        {"owner": {"login": "owner"}, "name": "repo", "default_branch": []},
        {"owner": {"login": ""}, "name": "repo", "default_branch": "main"},
        {"owner": {"login": 7}, "name": "repo", "default_branch": "main"},
        {"owner": {"login": "owner"}, "name": "", "default_branch": "main"},
        {"owner": {"login": "owner"}, "name": [], "default_branch": "main"},
    ],
)
async def test_repository_metadata_rejects_malformed_identity(payload):
    async def handler(_request):
        return httpx.Response(200, json=payload)

    adapter = make_adapter(handler)
    try:
        with pytest.raises(GitHubOperationalError, match="github_repository_response_invalid"):
            await adapter.repository_metadata()
    finally:
        await adapter.aclose()


def branch_response(ref: object, sha: object = "1" * 40) -> dict[str, object]:
    return {"ref": ref, "object": {"sha": sha}}


@pytest.mark.asyncio
async def test_branch_read_uses_heads_path_and_validates_identity():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json=branch_response("refs/heads/novalton/test-id"))

    adapter = make_adapter(handler)
    try:
        result = await adapter.branch_ref("novalton/test-id")
        assert result is not None and result.sha == "1" * 40
        assert str(requests[0].url) == (
            "https://api.github.com/repos/owner/repo/git/ref/heads/novalton/test-id"
        )
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        branch_response("refs/heads/novalton/other"),
        branch_response(None),
        branch_response("refs/heads/novalton/test-id", []),
    ],
)
async def test_branch_read_rejects_wrong_or_malformed_response(payload):
    async def handler(_request):
        return httpx.Response(200, json=payload)

    adapter = make_adapter(handler)
    try:
        with pytest.raises(GitHubOperationalError, match="github_ref_response_invalid"):
            await adapter.branch_ref("novalton/test-id")
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_branch_read_404_is_explicit_absence():
    async def handler(_request):
        return httpx.Response(404, json={"message": "not found"})

    adapter = make_adapter(handler)
    try:
        assert await adapter.branch_ref("novalton/test-id") is None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_branch_create_uses_canonical_ref_and_validates_response():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(201, json=branch_response("refs/heads/novalton/test-id"))

    adapter = make_adapter(handler)
    try:
        result = await adapter.create_branch("novalton/test-id", "1" * 40)
        assert result.sha == "1" * 40
        assert json.loads(requests[0].content)["ref"] == "refs/heads/novalton/test-id"
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_branch_create_rejects_wrong_returned_ref():
    async def handler(_request):
        return httpx.Response(201, json=branch_response("refs/heads/novalton/other"))

    adapter = make_adapter(handler)
    try:
        with pytest.raises(GitHubOperationalError, match="github_ref_response_invalid"):
            await adapter.create_branch("novalton/test-id", "1" * 40)
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_fixed_security_contract_and_sanitized_errors():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(500, content=b"distinctive-token internal details")

    adapter = make_adapter(handler)
    try:
        with pytest.raises(GitHubOperationalError, match="github_request_failed") as error:
            await adapter.repository_metadata()
        assert "distinctive-token" not in str(error.value)
        assert str(requests[0].url) == "https://api.github.com/repos/owner/repo"
        assert requests[0].headers["accept-encoding"] == "identity"
        assert requests[0].headers["x-github-api-version"] == "2022-11-28"
        assert adapter._client.follow_redirects is False
        assert adapter._client._trust_env is False
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_blob_sends_exact_bytes_and_returns_actual_valid_sha():
    content = b"exact object bytes\n"
    blob_sha = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(201, json={"sha": blob_sha})

    adapter = make_adapter(handler)
    try:
        assert await adapter.create_blob(content, blob_sha) == blob_sha
        assert json.loads(requests[0].content)["content"] == content.decode()
        assert await adapter.create_blob(content, "0" * 40) == blob_sha
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_redirect_and_oversized_stream_are_rejected():
    async def redirect(_):
        return httpx.Response(307, headers={"location": "https://evil.invalid"})

    adapter = make_adapter(redirect)
    try:
        with pytest.raises(GitHubOperationalError, match="github_request_failed"):
            await adapter.tree("a" * 40)
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"not-json", b"null"])
async def test_malformed_response_is_sanitized(content: bytes):
    async def malformed(_):
        return httpx.Response(200, content=content)

    adapter = make_adapter(malformed)
    try:
        with pytest.raises(GitHubOperationalError, match="github_response_invalid") as error:
            await adapter.repository_metadata()
        assert "distinctive-token" not in str(error.value)
    finally:
        await adapter.aclose()

    async def oversized(_):
        return httpx.Response(200, content=b"x" * 1025)

    adapter = make_adapter(oversized, limit=1024)
    try:
        with pytest.raises(GitHubOperationalError, match="github_response_too_large"):
            await adapter.repository_metadata()
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_transport_failure_is_bounded_operational_error_without_secret():
    async def handler(_request):
        raise httpx.ReadTimeout("Authorization: distinctive-token")

    adapter = make_adapter(handler)
    try:
        with pytest.raises(GitHubOperationalError, match="github_request_failed") as error:
            await adapter.repository_metadata()
        assert "distinctive-token" not in repr(error.value)
        assert "Authorization" not in repr(error.value)
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_commit_uses_actual_response_sha():
    requested = "1" * 40
    actual = "2" * 40

    async def handler(_request):
        return httpx.Response(
            200,
            json={
                "sha": actual,
                "tree": {"sha": "3" * 40},
                "parents": [{"sha": "4" * 40}],
                "commit": {
                    "message": "feat: exact",
                    "author": {
                        "name": "Novalton OS",
                        "email": "novalton@local.invalid",
                        "date": "2026-09-02T12:34:56+00:00",
                    },
                    "committer": {
                        "name": "Novalton OS",
                        "email": "novalton@local.invalid",
                        "date": "2026-09-02T12:34:56+00:00",
                    },
                },
            },
        )

    adapter = make_adapter(handler)
    try:
        result = await adapter.commit(requested)
        assert result is not None
        assert result.sha == actual
        assert result.sha != requested
    finally:
        await adapter.aclose()


def commit_payload(sha: object) -> dict[str, object]:
    return {
        "sha": sha,
        "tree": {"sha": "3" * 40},
        "parents": [{"sha": "4" * 40}],
        "commit": {
            "message": "feat: exact",
            "author": {
                "name": "Novalton OS",
                "email": "novalton@local.invalid",
                "date": "2026-09-02T12:34:56+00:00",
            },
            "committer": {
                "name": "Novalton OS",
                "email": "novalton@local.invalid",
                "date": "2026-09-02T12:34:56+00:00",
            },
        },
    }


@pytest.mark.asyncio
async def test_create_commit_returns_the_actual_response_sha():
    requested, actual = "1" * 40, "2" * 40
    responses = [requested, actual]

    async def handler(_request):
        return httpx.Response(201, json=commit_payload(responses.pop(0)))

    adapter = make_adapter(handler)
    try:
        exact = await adapter.create_commit(
            tree_sha="3" * 40,
            parent_sha="4" * 40,
            message="feat: exact",
            author="Novalton OS <novalton@local.invalid>",
            committer="Novalton OS <novalton@local.invalid>",
            timestamp=1_788_252_896,
            sha=requested,
        )
        assert exact.sha == requested
        different = await adapter.create_commit(
            tree_sha="3" * 40,
            parent_sha="4" * 40,
            message="feat: exact",
            author="Novalton OS <novalton@local.invalid>",
            committer="Novalton OS <novalton@local.invalid>",
            timestamp=1_788_252_896,
            sha=requested,
        )
        assert different.sha == actual
        assert different.sha != requested
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("sha", [None, 7, [], {}, "", "a" * 39, "g" * 40])
async def test_create_commit_malformed_response_sha_is_operational(sha: object):
    async def handler(_request):
        return httpx.Response(201, json=commit_payload(sha))

    adapter = make_adapter(handler)
    try:
        with pytest.raises(GitHubOperationalError, match="github_commit_response_invalid"):
            await adapter.create_commit(
                tree_sha="3" * 40,
                parent_sha="4" * 40,
                message="feat: exact",
                author="Novalton OS <novalton@local.invalid>",
                committer="Novalton OS <novalton@local.invalid>",
                timestamp=1_788_252_896,
                sha="1" * 40,
            )
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["base_ref", "branch_ref", "blob", "tree"])
@pytest.mark.parametrize("response", [{"object": {"sha": None}}, {"sha": []}])
async def test_typed_sha_responses_reject_malformed_values(
    method: str, response: dict[str, object]
):
    async def handler(_request):
        return httpx.Response(200, json=response)

    adapter = make_adapter(handler)
    try:
        argument = "refs/heads/novalton/action" if method == "branch_ref" else "1" * 40
        with pytest.raises(GitHubOperationalError):
            await getattr(adapter, method)(argument)
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_create_pull_request_rejects_malformed_typed_fields():
    async def handler(_request):
        return httpx.Response(201, json={"number": "7", "head": {}, "base": {}})

    adapter = make_adapter(handler)
    try:
        with pytest.raises(GitHubOperationalError, match="github_pull_request_response_invalid"):
            await adapter.create_pull_request(
                title="Title", body="Body", head="novalton/action", base="main"
            )
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"sha": "not-a-sha"}, {"sha": None}, {}])
async def test_commit_malformed_sha_is_operational_and_sanitized(payload):
    async def handler(_request):
        return httpx.Response(200, json=payload)

    adapter = make_adapter(handler)
    try:
        with pytest.raises(GitHubOperationalError, match="github_commit_response_invalid") as error:
            await adapter.commit("1" * 40)
        assert "distinctive-token" not in repr(error.value)
        assert "Authorization" not in repr(error.value)
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["tree", "parent", "message", "author"])
async def test_commit_required_fields_are_strictly_validated(field):
    payload = {
        "sha": "1" * 40,
        "tree": {"sha": "2" * 40},
        "parents": [{"sha": "3" * 40}],
        "commit": {
            "message": "feat: exact",
            "author": {
                "name": "Novalton OS",
                "email": "novalton@local.invalid",
                "date": "2026-09-02T12:34:56+00:00",
            },
            "committer": {
                "name": "Novalton OS",
                "email": "novalton@local.invalid",
                "date": "2026-09-02T12:34:56+00:00",
            },
        },
    }
    if field == "tree":
        payload["tree"]["sha"] = None
    elif field == "parent":
        payload["parents"][0]["sha"] = []
    elif field == "message":
        payload["commit"]["message"] = 7
    else:
        payload["commit"]["author"]["name"] = {"unexpected": True}

    async def handler(_request):
        return httpx.Response(200, json=payload)

    adapter = make_adapter(handler)
    try:
        with pytest.raises(GitHubOperationalError, match="github_commit_response_invalid"):
            await adapter.commit("1" * 40)
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_tree_and_commit_404_are_explicit_absence():
    async def handler(_request):
        return httpx.Response(404, json={"message": "not found"})

    adapter = make_adapter(handler)
    try:
        assert await adapter.tree("1" * 40) is None
        assert await adapter.commit("1" * 40) is None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_malformed_pull_request_item_is_operational_not_absence():
    async def handler(_request):
        return httpx.Response(200, json=[{"head": "malformed"}])

    adapter = make_adapter(handler)
    try:
        with pytest.raises(
            GitHubOperationalError, match="github_pull_request_response_invalid"
        ) as error:
            await adapter.find_pull_request(head="novalton/action", base="main")
        assert "distinctive-token" not in repr(error.value)
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_valid_nonmatching_pull_request_list_is_absence():
    async def handler(_request):
        return httpx.Response(
            200,
            json=[
                {
                    "number": 7,
                    "html_url": "https://github.com/owner/repo/pull/7",
                    "title": "Other",
                    "body": "Body",
                    "head": {"sha": "1" * 40, "ref": "other"},
                    "base": {"ref": "main"},
                }
            ],
        )

    adapter = make_adapter(handler)
    try:
        assert await adapter.find_pull_request(head="novalton/action", base="main") is None
    finally:
        await adapter.aclose()


def test_closed_surface_has_no_generic_or_dangerous_operations():
    names = set(dir(GitHubHttpAdapter))
    forbidden = {
        "request",
        "update_ref",
        "force_update_ref",
        "delete_ref",
        "merge",
        "review",
        "comment",
        "close",
        "graphql",
        "issue",
        "settings",
        "workflow",
        "secret",
    }
    assert not any(name in names for name in forbidden)
