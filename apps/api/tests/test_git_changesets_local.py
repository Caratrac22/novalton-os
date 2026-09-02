"""Provider-free tests for the closed local Dulwich commit adapter."""

import hashlib
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dulwich.index import Index, IndexEntry
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo

from novalton_api.modules.git_changesets import local
from novalton_api.modules.tools.executor import ToolExecutionError, WorkspaceRoot


def _commit(repo: Repo, blob: Blob) -> Commit:
    tree = Tree()
    tree.add(b"fixture.txt", 0o100644, blob.id)
    repo.object_store.add_object(tree)
    commit = Commit()
    commit.tree = tree.id
    commit.parents = []
    commit.author = b"Fixture <fixture@local.invalid>"
    commit.committer = commit.author
    commit.message = b"initial"
    commit.author_time = commit.commit_time = 1
    commit.author_timezone = commit.commit_timezone = 0
    repo.object_store.add_object(commit)
    repo.refs[b"refs/heads/master"] = commit.id
    return commit


def _repository(tmp_path: Path) -> tuple[WorkspaceRoot, Repo, bytes]:
    repo = Repo.init(tmp_path)
    path = tmp_path / "fixture.txt"
    path.write_text("before\n", encoding="utf-8")
    blob = Blob.from_string(path.read_bytes())
    repo.object_store.add_object(blob)
    _commit(repo, blob)
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
    return WorkspaceRoot.approved(tmp_path), repo, blob.id


def test_prepare_and_apply_creates_one_exact_local_commit(tmp_path: Path) -> None:
    root, repo, _ = _repository(tmp_path)
    initial = repo.head()
    target = tmp_path / "fixture.txt"
    target.write_text("after\n", encoding="utf-8")
    candidate = hashlib.sha256(target.read_bytes()).hexdigest()
    prepared = local.prepare(
        root,
        [
            {
                "path": "fixture.txt",
                "preimage_sha256": hashlib.sha256(b"before\n").hexdigest(),
                "candidate_sha256": candidate,
            }
        ],
    )
    timestamp = datetime(2026, 9, 2, tzinfo=UTC)
    expected = local.expected_commit_sha(
        root,
        prepared,
        message="feat: exact fixture",
        identity="Novalton OS <novalton@local.invalid>",
        timestamp=timestamp,
    )
    assert repo.head() == initial
    action_paths = [
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
    sha = local.apply(
        root,
        action_paths,
        expected_head=prepared.head_sha,
        expected_index=prepared.index_fingerprint,
        branch_ref=prepared.branch_ref,
        message="feat: exact fixture",
        identity="Novalton OS <novalton@local.invalid>",
        timestamp=timestamp,
        expected_commit=expected,
    )
    assert sha == expected
    # Simulate a crash after ref CAS but before the eligible index entry is refreshed.
    index = Index(repo.index_path())
    entry = index[b"fixture.txt"]
    index[b"fixture.txt"] = IndexEntry(
        entry.ctime,
        entry.mtime,
        entry.dev,
        entry.ino,
        entry.mode,
        entry.uid,
        entry.gid,
        entry.size,
        prepared.paths[0].head_blob_id.encode(),
    )
    index.write()
    assert (
        local.apply(
            root,
            action_paths,
            expected_head=prepared.head_sha,
            expected_index=prepared.index_fingerprint,
            branch_ref=prepared.branch_ref,
            message="feat: exact fixture",
            identity="Novalton OS <novalton@local.invalid>",
            timestamp=timestamp,
            expected_commit=expected,
        )
        == expected
    )
    assert (
        Index(repo.index_path())[b"fixture.txt"].sha == prepared.paths[0].candidate_blob_id.encode()
    )


def test_preexisting_target_and_stale_worktree_fail_closed(tmp_path: Path) -> None:
    root, _, _ = _repository(tmp_path)
    target = tmp_path / "fixture.txt"
    target.write_text("unrelated\n", encoding="utf-8")
    with pytest.raises(ToolExecutionError, match="git_preexisting_target_dirty"):
        local.prepare(
            root,
            [{"path": "fixture.txt", "preimage_sha256": "0" * 64, "candidate_sha256": "0" * 64}],
        )


def test_unrelated_staged_entry_is_preserved_and_never_committed(tmp_path: Path) -> None:
    root, repo, _ = _repository(tmp_path)
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("operator staged\n", encoding="utf-8")
    staged = Blob.from_string(unrelated.read_bytes())
    repo.object_store.add_object(staged)
    index = Index(repo.index_path())
    metadata = unrelated.stat()
    index[b"unrelated.txt"] = IndexEntry(
        (int(metadata.st_ctime), 0),
        (int(metadata.st_mtime), 0),
        metadata.st_dev,
        metadata.st_ino,
        0o100644,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        staged.id,
    )
    index.write()
    unrelated_before = Index(repo.index_path())[b"unrelated.txt"]
    target = tmp_path / "fixture.txt"
    target.write_text("after\n", encoding="utf-8")
    prepared = local.prepare(
        root,
        [
            {
                "path": "fixture.txt",
                "preimage_sha256": hashlib.sha256(b"before\n").hexdigest(),
                "candidate_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        ],
    )
    timestamp = datetime(2026, 9, 2, tzinfo=UTC)
    expected = local.expected_commit_sha(
        root,
        prepared,
        message="fix: fixture",
        identity="Novalton OS <novalton@local.invalid>",
        timestamp=timestamp,
    )
    local.apply(
        root,
        [
            {
                "path": item.path,
                "preimage_sha256": item.head_sha256,
                "candidate_sha256": item.candidate_sha256,
                "mode": item.mode,
                "head_blob_id": item.head_blob_id,
                "candidate_blob_id": item.candidate_blob_id,
            }
            for item in prepared.paths
        ],
        expected_head=prepared.head_sha,
        expected_index=prepared.index_fingerprint,
        branch_ref=prepared.branch_ref,
        message="fix: fixture",
        identity="Novalton OS <novalton@local.invalid>",
        timestamp=timestamp,
        expected_commit=expected,
    )
    assert Index(repo.index_path())[b"unrelated.txt"] == unrelated_before
    commit = repo.object_store[repo.head()]
    assert isinstance(commit, Commit)
    tree = repo.object_store[commit.tree]
    assert isinstance(tree, Tree)
    assert b"unrelated.txt" not in tree


def test_adapter_never_invokes_process_or_network_entry_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = _repository(tmp_path)
    target = tmp_path / "fixture.txt"
    target.write_text("after\n", encoding="utf-8")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("forbidden external execution")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    prepared = local.prepare(
        root,
        [
            {
                "path": "fixture.txt",
                "preimage_sha256": hashlib.sha256(b"before\n").hexdigest(),
                "candidate_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        ],
    )
    assert prepared.preview["diff_truncated"] is False


def test_stale_index_fails_closed(tmp_path: Path) -> None:
    root, repo, _ = _repository(tmp_path)
    target = tmp_path / "fixture.txt"
    target.write_text("after\n", encoding="utf-8")
    prepared = local.prepare(
        root,
        [
            {
                "path": "fixture.txt",
                "preimage_sha256": hashlib.sha256(b"before\n").hexdigest(),
                "candidate_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        ],
    )
    timestamp = datetime(2026, 9, 2, tzinfo=UTC)
    expected = local.expected_commit_sha(
        root,
        prepared,
        message="fix: fixture",
        identity="Novalton OS <novalton@local.invalid>",
        timestamp=timestamp,
    )
    action_paths = [
        {
            "path": item.path,
            "candidate_sha256": item.candidate_sha256,
            "mode": item.mode,
            "head_blob_id": item.head_blob_id,
            "candidate_blob_id": item.candidate_blob_id,
        }
        for item in prepared.paths
    ]
    index = Index(repo.index_path())
    index[b"unrelated.txt"] = IndexEntry((1, 0), (1, 0), 0, 0, 0o100644, 0, 0, 0, b"0" * 40)
    index.write()
    with pytest.raises(ToolExecutionError, match="git_stale_index"):
        local.apply(
            root,
            action_paths,
            expected_head=prepared.head_sha,
            expected_index=prepared.index_fingerprint,
            branch_ref=prepared.branch_ref,
            message="fix: fixture",
            identity="Novalton OS <novalton@local.invalid>",
            timestamp=timestamp,
            expected_commit=expected,
        )


def test_stale_head_fails_closed(tmp_path: Path) -> None:
    root, repo, _ = _repository(tmp_path)
    target = tmp_path / "fixture.txt"
    target.write_text("after\n", encoding="utf-8")
    prepared = local.prepare(
        root,
        [
            {
                "path": "fixture.txt",
                "preimage_sha256": hashlib.sha256(b"before\n").hexdigest(),
                "candidate_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        ],
    )
    timestamp = datetime(2026, 9, 2, tzinfo=UTC)
    expected = local.expected_commit_sha(
        root,
        prepared,
        message="fix: fixture",
        identity="Novalton OS <novalton@local.invalid>",
        timestamp=timestamp,
    )
    current = repo.object_store[repo.head()]
    assert isinstance(current, Commit)
    other = Commit()
    other.tree = current.tree
    other.parents = [current.id]
    other.author = other.committer = b"Fixture <fixture@local.invalid>"
    other.message = b"other"
    other.author_time = other.commit_time = 2
    other.author_timezone = other.commit_timezone = 0
    repo.object_store.add_object(other)
    repo.refs[b"refs/heads/master"] = other.id
    with pytest.raises(ToolExecutionError, match="git_stale_head"):
        local.apply(
            root,
            [
                {
                    "path": item.path,
                    "candidate_sha256": item.candidate_sha256,
                    "mode": item.mode,
                    "head_blob_id": item.head_blob_id,
                    "candidate_blob_id": item.candidate_blob_id,
                }
                for item in prepared.paths
            ],
            expected_head=prepared.head_sha,
            expected_index=prepared.index_fingerprint,
            branch_ref=prepared.branch_ref,
            message="fix: fixture",
            identity="Novalton OS <novalton@local.invalid>",
            timestamp=timestamp,
            expected_commit=expected,
        )
