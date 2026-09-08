"""The only production GitHub transport: fixed-host, typed, bounded calls."""

import json
import re
from datetime import datetime
from typing import Any

import httpx
from pydantic import SecretStr

from novalton_api.modules.github_publications.adapter import (
    GitHubOperationalError,
    RemoteBlob,
    RemoteCommit,
    RemotePullRequest,
    RemoteRef,
    RemoteTree,
)
from novalton_api.modules.github_publications.config import GitHubBinding

_SHA = re.compile(r"^[0-9a-f]{40}$")


def _required_text(
    value: object,
    code: str,
    *,
    allow_empty: bool = False,
    max_length: int | None = None,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise GitHubOperationalError(code)
    if max_length is not None and len(value) > max_length:
        raise GitHubOperationalError(code)
    return value


def _required_sha(value: object, code: str) -> str:
    result = _required_text(value, code)
    if not _SHA.fullmatch(result):
        raise GitHubOperationalError(code)
    return result


def _ref_sha(value: object, code: str) -> str:
    if not isinstance(value, dict):
        raise GitHubOperationalError(code)
    return _required_sha(value.get("sha"), code)


def _branch_parts(ref: str) -> tuple[str, str]:
    if not isinstance(ref, str):
        raise GitHubOperationalError("github_ref_response_invalid")
    branch = ref.removeprefix("refs/heads/")
    if (
        not branch
        or branch.startswith("refs/")
        or branch.startswith("/")
        or len(branch) > 255
        or "\x00" in branch
    ):
        raise GitHubOperationalError("github_ref_response_invalid")
    return branch, f"refs/heads/{branch}"


def _parse_ref(value: object, expected_ref: str, code: str) -> RemoteRef:
    if not isinstance(value, dict):
        raise GitHubOperationalError(code)
    actual_ref = _required_text(value.get("ref"), code, max_length=255)
    if actual_ref != expected_ref:
        raise GitHubOperationalError(code)
    return RemoteRef(_ref_sha(value.get("object"), code))


class GitHubHttpAdapter:
    def __init__(
        self,
        binding: GitHubBinding,
        token: SecretStr,
        *,
        timeout: httpx.Timeout | None = None,
        max_response_bytes: int = 1_048_576,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._binding = binding
        self._max = max_response_bytes
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            follow_redirects=False,
            trust_env=False,
            timeout=timeout or httpx.Timeout(30.0, connect=5.0, read=30.0, write=10.0, pool=5.0),
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Accept-Encoding": "identity",
                "Authorization": f"Bearer {token.get_secret_value()}",
            },
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._client.get(path, **kwargs)
        except httpx.HTTPError:
            raise GitHubOperationalError("github_request_failed") from None

    async def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._client.post(path, **kwargs)
        except httpx.HTTPError:
            raise GitHubOperationalError("github_request_failed") from None

    async def _json(self, response: httpx.Response) -> dict[str, Any] | list[Any]:
        if 300 <= response.status_code < 400 or response.status_code >= 400:
            raise GitHubOperationalError("github_request_failed")
        chunks = bytearray()
        try:
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > self._max:
                    raise GitHubOperationalError("github_response_too_large")
        except httpx.HTTPError:
            raise GitHubOperationalError("github_response_read_failed") from None
        try:
            value = json.loads(bytes(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GitHubOperationalError("github_response_invalid") from None
        if not isinstance(value, (dict, list)):
            raise GitHubOperationalError("github_response_invalid")
        return value

    async def repository_metadata(self) -> dict[str, object]:
        value = await self._json(
            await self._get(f"/repos/{self._binding.owner}/{self._binding.repository}")
        )
        if not isinstance(value, dict):
            raise GitHubOperationalError("github_response_invalid")
        owner = value.get("owner")
        code = "github_repository_response_invalid"
        if not isinstance(owner, dict):
            raise GitHubOperationalError("github_repository_response_invalid")
        owner_login = _required_text(owner.get("login"), code, max_length=39)
        repository = _required_text(value.get("name"), code, max_length=100)
        default_branch = _required_text(value.get("default_branch"), code, max_length=255)
        return {
            "provider": "github",
            "owner": owner_login,
            "repository": repository,
            "default_branch": default_branch,
        }

    async def base_ref(self, branch: str) -> RemoteRef:
        branch_name, expected_ref = _branch_parts(branch)
        value = await self._json(
            await self._get(
                f"/repos/{self._binding.owner}/{self._binding.repository}/git/ref/heads/{branch_name}"
            )
        )
        if not isinstance(value, dict):
            raise GitHubOperationalError("github_response_invalid")
        return _parse_ref(value, expected_ref, "github_ref_response_invalid")

    async def branch_ref(self, ref: str) -> RemoteRef | None:
        branch_name, expected_ref = _branch_parts(ref)
        response = await self._get(
            f"/repos/{self._binding.owner}/{self._binding.repository}/git/ref/heads/{branch_name}"
        )
        if response.status_code == 404:
            return None
        value = await self._json(response)
        if not isinstance(value, dict):
            raise GitHubOperationalError("github_response_invalid")
        return _parse_ref(value, expected_ref, "github_ref_response_invalid")

    async def create_branch(self, ref: str, sha: str) -> RemoteRef:
        _, expected_ref = _branch_parts(ref)
        value = await self._json(
            await self._post(
                f"/repos/{self._binding.owner}/{self._binding.repository}/git/refs",
                json={"ref": expected_ref, "sha": sha},
            )
        )
        if not isinstance(value, dict):
            raise GitHubOperationalError("github_response_invalid")
        return _parse_ref(value, expected_ref, "github_ref_response_invalid")

    async def create_blob(self, content: bytes, sha: str) -> str:
        value = await self._json(
            await self._post(
                f"/repos/{self._binding.owner}/{self._binding.repository}/git/blobs",
                json={"content": content.decode("utf-8"), "encoding": "utf-8"},
            )
        )
        if not isinstance(value, dict):
            raise GitHubOperationalError("github_response_invalid")
        return _required_sha(value.get("sha"), "github_blob_response_invalid")

    async def blob(self, sha: str) -> RemoteBlob | None:
        response = await self._get(
            f"/repos/{self._binding.owner}/{self._binding.repository}/git/blobs/{sha}"
        )
        if response.status_code == 404:
            return None
        value = await self._json(response)
        if not isinstance(value, dict):
            raise GitHubOperationalError("github_response_invalid")
        result = value.get("sha")
        return RemoteBlob(_required_sha(result, "github_blob_response_invalid"))

    async def tree(self, sha: str) -> RemoteTree | None:
        response = await self._get(
            f"/repos/{self._binding.owner}/{self._binding.repository}/git/trees/{sha}"
        )
        if response.status_code == 404:
            return None
        value = await self._json(response)
        if not isinstance(value, dict):
            raise GitHubOperationalError("github_response_invalid")
        result = value.get("sha")
        if not isinstance(result, str) or not _SHA.fullmatch(result):
            raise GitHubOperationalError("github_tree_response_invalid")
        return RemoteTree(result)

    async def create_tree(
        self, base_tree_sha: str, entries: list[dict[str, object]], sha: str
    ) -> str:
        value = await self._json(
            await self._post(
                f"/repos/{self._binding.owner}/{self._binding.repository}/git/trees",
                json={"base_tree": base_tree_sha, "tree": entries},
            )
        )
        if not isinstance(value, dict):
            raise GitHubOperationalError("github_response_invalid")
        return _required_sha(value.get("sha"), "github_tree_response_invalid")

    async def commit(self, sha: str) -> RemoteCommit | None:
        response = await self._get(
            f"/repos/{self._binding.owner}/{self._binding.repository}/git/commits/{sha}"
        )
        if response.status_code == 404:
            return None
        value = await self._json(response)
        if not isinstance(value, dict):
            raise GitHubOperationalError("github_response_invalid")

        return self._parse_commit(value)

    @staticmethod
    def _parse_commit(value: object) -> RemoteCommit:
        if not isinstance(value, dict):
            raise GitHubOperationalError("github_commit_response_invalid")
        response_sha = _required_sha(value.get("sha"), "github_commit_response_invalid")
        parents = value.get("parents")
        c = value.get("commit")
        tree = value.get("tree")
        if (
            not isinstance(parents, list)
            or len(parents) != 1
            or not isinstance(parents[0], dict)
            or not isinstance(c, dict)
            or not isinstance(tree, dict)
        ):
            raise GitHubOperationalError("github_commit_response_invalid")
        author = c.get("author", {})
        committer = c.get("committer", {})
        if not isinstance(author, dict) or not isinstance(committer, dict):
            raise GitHubOperationalError("github_commit_response_invalid")
        author_name = _required_text(author.get("name"), "github_commit_response_invalid")
        author_email = _required_text(author.get("email"), "github_commit_response_invalid")
        committer_name = _required_text(committer.get("name"), "github_commit_response_invalid")
        committer_email = _required_text(committer.get("email"), "github_commit_response_invalid")
        message = _required_text(c.get("message"), "github_commit_response_invalid")
        tree_sha = _required_sha(tree.get("sha"), "github_commit_response_invalid")
        parent_sha = _required_sha(parents[0].get("sha"), "github_commit_response_invalid")

        def parsed_date(value: object) -> tuple[int, int]:
            if not isinstance(value, str):
                raise GitHubOperationalError("github_commit_response_invalid")
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise GitHubOperationalError("github_commit_response_invalid") from None
            if parsed.utcoffset() is None:
                raise GitHubOperationalError("github_commit_response_invalid")
            offset = int(parsed.utcoffset().total_seconds())
            return int(parsed.timestamp()), offset

        author_timestamp, author_timezone = parsed_date(author.get("date"))
        committer_timestamp, committer_timezone = parsed_date(committer.get("date"))
        return RemoteCommit(
            sha=response_sha,
            tree_sha=tree_sha,
            parent_sha=parent_sha,
            message=message,
            author=f"{author_name} <{author_email}>",
            committer=f"{committer_name} <{committer_email}>",
            timestamp=author_timestamp,
            author_timestamp=author_timestamp,
            committer_timestamp=committer_timestamp,
            author_timezone=author_timezone,
            committer_timezone=committer_timezone,
        )

    async def create_commit(
        self,
        *,
        tree_sha: str,
        parent_sha: str,
        message: str,
        author: str,
        committer: str,
        timestamp: int,
        sha: str,
    ) -> RemoteCommit:
        def identity(value: str) -> dict[str, str]:
            name, _, email = value.partition(" <")
            return {"name": name, "email": email.removesuffix(">") or name}

        from datetime import UTC, datetime

        date = datetime.fromtimestamp(timestamp, UTC).isoformat()
        value = await self._json(
            await self._post(
                f"/repos/{self._binding.owner}/{self._binding.repository}/git/commits",
                json={
                    "message": message,
                    "tree": tree_sha,
                    "parents": [parent_sha],
                    "author": {**identity(author), "date": date},
                    "committer": {**identity(committer), "date": date},
                },
            )
        )
        if not isinstance(value, dict):
            raise GitHubOperationalError("github_response_invalid")
        return self._parse_commit(value)

    async def find_pull_request(self, *, head: str, base: str) -> RemotePullRequest | None:
        value = await self._json(
            await self._get(
                f"/repos/{self._binding.owner}/{self._binding.repository}/pulls",
                params={"state": "all", "head": f"{self._binding.owner}:{head}", "base": base},
            )
        )
        if not isinstance(value, list):
            raise GitHubOperationalError("github_response_invalid")
        for item in value:
            candidate = self._parse_pull_request(item)
            if candidate.head_ref == head and candidate.base_ref == base:
                return candidate
        return None

    @staticmethod
    def _parse_pull_request(value: object) -> RemotePullRequest:
        code = "github_pull_request_response_invalid"
        if not isinstance(value, dict):
            raise GitHubOperationalError(code)
        head_value, base_value = value.get("head"), value.get("base")
        if not isinstance(head_value, dict) or not isinstance(base_value, dict):
            raise GitHubOperationalError(code)
        number = value.get("number")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise GitHubOperationalError(code)
        body_value = value.get("body")
        if body_value is not None and not isinstance(body_value, str):
            raise GitHubOperationalError(code)
        return RemotePullRequest(
            number=number,
            url=_required_text(value.get("html_url"), code),
            head_sha=_required_sha(head_value.get("sha"), code),
            title=_required_text(value.get("title"), code),
            body=body_value or "",
            head_ref=_required_text(head_value.get("ref"), code),
            base_ref=_required_text(base_value.get("ref"), code),
        )

    async def create_pull_request(
        self, *, title: str, body: str, head: str, base: str
    ) -> RemotePullRequest:
        value = await self._json(
            await self._post(
                f"/repos/{self._binding.owner}/{self._binding.repository}/pulls",
                json={"title": title, "body": body, "head": head, "base": base},
            )
        )
        return self._parse_pull_request(value)
