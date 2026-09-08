"""Typed closed-world GitHub operations; no caller-controlled URL or request surface."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import SecretStr


class GitHubOperationalError(RuntimeError):
    """Sanitized, bounded failures from the GitHub transport/provider."""


@dataclass(frozen=True)
class RemoteCommit:
    sha: str
    tree_sha: str
    parent_sha: str
    message: str
    author: str
    committer: str
    timestamp: int
    author_timestamp: int | None = None
    committer_timestamp: int | None = None
    author_timezone: int | None = None
    committer_timezone: int | None = None


@dataclass(frozen=True)
class RemoteTree:
    sha: str


@dataclass(frozen=True)
class RemoteBlob:
    sha: str


@dataclass(frozen=True)
class RemoteRef:
    sha: str


@dataclass(frozen=True)
class RemotePullRequest:
    number: int
    url: str
    head_sha: str
    title: str
    body: str
    head_ref: str
    base_ref: str


class GitHubPublicationAdapter(Protocol):
    async def repository_metadata(self) -> dict[str, object]: ...
    async def base_ref(self, branch: str) -> RemoteRef: ...
    async def blob(self, sha: str) -> RemoteBlob | None: ...
    async def commit(self, sha: str) -> RemoteCommit | None: ...
    async def tree(self, sha: str) -> RemoteTree | None: ...
    async def create_blob(self, content: bytes, sha: str) -> str: ...
    async def create_tree(
        self, base_tree_sha: str, entries: list[dict[str, object]], sha: str
    ) -> str: ...
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
    ) -> RemoteCommit: ...
    async def branch_ref(self, ref: str) -> RemoteRef | None: ...
    async def create_branch(self, ref: str, sha: str) -> RemoteRef: ...
    async def find_pull_request(self, *, head: str, base: str) -> RemotePullRequest | None: ...
    async def create_pull_request(
        self, *, title: str, body: str, head: str, base: str
    ) -> RemotePullRequest: ...


class GitHubCredentialResolver(Protocol):
    def resolve(self) -> SecretStr: ...
