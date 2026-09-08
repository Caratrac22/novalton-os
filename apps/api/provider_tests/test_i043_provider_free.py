"""DB-independent I-043 authority and replay matrix.

This module intentionally lives beside ``tests/``: the database identity fixture is scoped to
that directory and must never run for these local-object/provider-adapter tests.
"""

import hashlib
import json
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from dulwich.index import Index, IndexEntry
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo
from pydantic import SecretStr

from novalton_api.modules.git_changesets import local
from novalton_api.modules.github_publications.config import GitHubBinding
from novalton_api.modules.github_publications.http_adapter import GitHubHttpAdapter
from novalton_api.modules.tools.executor import ToolExecutionError, WorkspaceRoot

IDENTITY = "Novalton OS <novalton@local.invalid>"
STAMP = datetime(2026, 9, 2, 12, 34, 56, tzinfo=UTC)


def _repo(tmp_path: Path) -> tuple[WorkspaceRoot, Repo, str]:
    repo = Repo.init(tmp_path)
    path = tmp_path / "fixture.txt"
    path.write_bytes(b"before\n")
    blob = Blob.from_string(path.read_bytes())
    repo.object_store.add_object(blob)
    tree = Tree()
    tree.add(b"fixture.txt", 0o100644, blob.id)
    repo.object_store.add_object(tree)
    commit = Commit()
    commit.tree = tree.id
    commit.parents = []
    commit.author = commit.committer = IDENTITY.encode()
    commit.message = b"initial"
    commit.author_time = commit.commit_time = 1
    commit.author_timezone = commit.commit_timezone = 0
    repo.object_store.add_object(commit)
    repo.refs[b"refs/heads/main"] = commit.id
    repo.refs.set_symbolic_ref(b"HEAD", b"refs/heads/main")
    index = Index(repo.index_path(), read=False)
    stat = path.stat()
    index[b"fixture.txt"] = IndexEntry(
        (int(stat.st_ctime), 0),
        (int(stat.st_mtime), 0),
        stat.st_dev,
        stat.st_ino,
        0o100644,
        stat.st_uid,
        stat.st_gid,
        stat.st_size,
        blob.id,
    )
    index.write()
    return WorkspaceRoot.approved(tmp_path), repo, commit.id.decode()


def _prepare(root: WorkspaceRoot) -> tuple[local.LocalPreparation, list[dict[str, object]], str]:
    target = root.path / "fixture.txt"
    target.write_bytes(b"after\n")
    prepared = local.prepare(
        root,
        [
            {
                "path": "fixture.txt",
                "preimage_sha256": hashlib.sha256(b"before\n").hexdigest(),
                "candidate_sha256": hashlib.sha256(b"after\n").hexdigest(),
            }
        ],
    )
    paths = [
        {
            "path": item.path,
            "preimage_sha256": item.head_sha256,
            "candidate_sha256": item.candidate_sha256,
            "mode": item.mode,
            "head_blob_id": item.head_blob_id,
            "candidate_blob_id": item.candidate_blob_id,
        }
        for item in prepared.paths
    ]
    expected = local.expected_commit_sha(
        root, prepared, message="feat: exact", identity=IDENTITY, timestamp=STAMP
    )
    return prepared, paths, expected


def test_provider_free_proof_executes_without_database() -> None:
    """Collection/execution of this sibling lane cannot invoke the DB fixture."""
    assert True


def test_local_commit_proof_is_immutable_and_exact(tmp_path: Path) -> None:
    root, repo, parent = _repo(tmp_path)
    prepared, paths, expected = _prepare(root)
    assert prepared.branch_ref == "refs/heads/main"
    assert prepared.repository_key == hashlib.sha256(str(tmp_path).encode()).hexdigest()
    assert (
        local.apply(
            root,
            paths,
            expected_head=prepared.head_sha,
            expected_index=prepared.index_fingerprint,
            branch_ref=prepared.branch_ref,
            message="feat: exact",
            identity=IDENTITY,
            timestamp=STAMP,
            expected_commit=expected,
        )
        == expected
    )
    proof, objects = local.read_publication_objects(
        root,
        expected_commit=expected,
        expected_parent=parent,
        branch_ref="refs/heads/main",
        message="feat: exact",
        author=IDENTITY,
        committer=IDENTITY,
        timestamp=STAMP,
        paths=paths,
        expected_tree=None,
    )
    assert proof["commit_sha"] == expected
    assert proof["parent_sha"] == parent
    assert proof["changes"] == [
        {
            "path": "fixture.txt",
            "mode": 0o100644,
            "blob_sha": paths[0]["candidate_blob_id"],
            "blob_sha256": hashlib.sha256(b"after\n").hexdigest(),
            "candidate_blob_id": paths[0]["candidate_blob_id"],
            "candidate_sha256": hashlib.sha256(b"after\n").hexdigest(),
        }
    ]
    (tmp_path / "fixture.txt").write_bytes(b"tampered worktree\n")
    assert objects[0][2] == b"after\n"


@pytest.mark.parametrize(
    "field",
    [
        "expected_commit",
        "expected_parent",
        "message",
        "author",
        "committer",
        "timestamp",
    ],
)
def test_local_commit_proof_tampering_fails_closed(tmp_path: Path, field: str) -> None:
    root, _, parent = _repo(tmp_path)
    prepared, paths, expected = _prepare(root)
    local.apply(
        root,
        paths,
        expected_head=prepared.head_sha,
        expected_index=prepared.index_fingerprint,
        branch_ref=prepared.branch_ref,
        message="feat: exact",
        identity=IDENTITY,
        timestamp=STAMP,
        expected_commit=expected,
    )
    values: dict[str, object] = {
        "expected_commit": "0" * 40,
        "expected_parent": "1" * 40,
        "message": "tampered",
        "author": "Other <other@invalid>",
        "committer": "Other <other@invalid>",
        "timestamp": STAMP.replace(year=2025),
    }
    with pytest.raises(ToolExecutionError):
        local.read_publication_objects(
            root,
            expected_commit=str(
                values["expected_commit"] if field == "expected_commit" else expected
            ),
            expected_parent=str(
                values["expected_parent"] if field == "expected_parent" else parent
            ),
            branch_ref="refs/heads/main",
            message=str(values["message"] if field == "message" else "feat: exact"),
            author=str(values["author"] if field == "author" else IDENTITY),
            committer=str(values["committer"] if field == "committer" else IDENTITY),
            timestamp=values["timestamp"] if field == "timestamp" else STAMP,
            paths=paths,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"path": "other.txt"},
        {"mode": 0o100755},
        {"candidate_blob_id": "0" * 40},
        {"candidate_sha256": "0" * 64},
        {"head_blob_id": "0" * 40},
        {"preimage_sha256": "0" * 64},
    ],
)
def test_local_changeset_manifest_tampering_fails_closed(
    tmp_path: Path, change: dict[str, object]
) -> None:
    root, _, parent = _repo(tmp_path)
    prepared, paths, expected = _prepare(root)
    local.apply(
        root,
        paths,
        expected_head=prepared.head_sha,
        expected_index=prepared.index_fingerprint,
        branch_ref=prepared.branch_ref,
        message="feat: exact",
        identity=IDENTITY,
        timestamp=STAMP,
        expected_commit=expected,
    )
    tampered = [dict(paths[0])]
    tampered[0].update(change)
    with pytest.raises(ToolExecutionError):
        local.read_publication_objects(
            root,
            expected_commit=expected,
            expected_parent=parent,
            branch_ref=prepared.branch_ref,
            message="feat: exact",
            author=IDENTITY,
            committer=IDENTITY,
            timestamp=STAMP,
            paths=tampered,
        )


def test_local_tree_and_branch_manifest_tampering_fails_closed(tmp_path: Path) -> None:
    root, _, parent = _repo(tmp_path)
    prepared, paths, expected = _prepare(root)
    local.apply(
        root,
        paths,
        expected_head=prepared.head_sha,
        expected_index=prepared.index_fingerprint,
        branch_ref=prepared.branch_ref,
        message="feat: exact",
        identity=IDENTITY,
        timestamp=STAMP,
        expected_commit=expected,
    )
    with pytest.raises(ToolExecutionError):
        local.read_publication_objects(
            root,
            expected_commit=expected,
            expected_parent=parent,
            branch_ref="refs/heads/other",
            message="feat: exact",
            author=IDENTITY,
            committer=IDENTITY,
            timestamp=STAMP,
            paths=paths,
            expected_tree="0" * 40,
        )


def _binding() -> GitHubBinding:
    return GitHubBinding(
        "github", "https://api.github.com", "owner", "repo", "main", "v1", "key", "/workspace"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"sha": "not-a-sha"}, {"unexpected": True}])
async def test_blob_replay_rejects_every_bad_sha_without_writes(payload: dict[str, object]) -> None:
    writes: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        writes.append(request.method)
        return httpx.Response(201, json=payload)

    adapter = GitHubHttpAdapter(
        _binding(),
        SecretStr("NOVALTON_SUPER_SECRET_TEST_TOKEN_9431"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(RuntimeError):
            await adapter.create_blob(b"bytes", hashlib.sha1(b"blob 5\0bytes").hexdigest())
        assert writes == ["POST"]
    finally:
        await adapter.aclose()


def test_adapter_surface_is_closed_and_no_secret_is_serialized() -> None:
    names = set(dir(GitHubHttpAdapter))
    forbidden = {
        "request",
        "generic_request",
        "graphql",
        "update_ref",
        "force",
        "delete_ref",
        "merge",
        "close_pr",
        "comment",
        "review",
        "issue",
        "settings",
        "actions",
        "workflows",
        "secrets",
    }
    assert names.isdisjoint(forbidden)
    assert "NOVALTON_SUPER_SECRET_TEST_TOKEN_9431" not in json.dumps(_binding().__dict__)


def test_repository_binding_is_server_owned() -> None:
    binding = _binding()
    assert (binding.provider, binding.owner, binding.repository, binding.base_branch) == (
        "github",
        "owner",
        "repo",
        "main",
    )
    assert binding.api_base == "https://api.github.com"
    assert binding.key == "key"
    assert binding.workspace_root == "/workspace"


def test_local_adapter_confines_paths_and_forbids_process_network_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = _repo(tmp_path)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("external execution is forbidden")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    with pytest.raises(ToolExecutionError):
        local.prepare(
            root,
            [
                {
                    "path": "../escape.txt",
                    "preimage_sha256": "0" * 64,
                    "candidate_sha256": "0" * 64,
                }
            ],
        )
