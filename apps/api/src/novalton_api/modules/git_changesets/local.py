"""Small, closed-world Dulwich adapter for one local commit changeset.

This module deliberately imports only local object, ref, repository and index APIs.
It never imports Dulwich porcelain, transports, clients, hooks or subprocess helpers.
"""

import difflib
import hashlib
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dulwich.index import Index, IndexEntry
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo

from novalton_api.modules.tools.executor import ToolExecutionError, WorkspaceRoot, _denied

_MAX_DIFF_BYTES = 32_768
_REGULAR_MODES = {0o100644, 0o100755}


@dataclass(frozen=True)
class PreparedPath:
    path: str
    head_sha256: str
    candidate_sha256: str
    mode: int
    head_blob_id: str
    candidate_blob_id: str


@dataclass(frozen=True)
class LocalPreparation:
    repository_key: str
    branch_ref: str
    head_sha: str
    index_fingerprint: str
    paths: tuple[PreparedPath, ...]
    preview: dict[str, object]
    tree_id: str


def _error(code: str) -> ToolExecutionError:
    return ToolExecutionError(code)


def _hex(value: bytes) -> str:
    return value.decode("ascii")


def _git_dir(root: WorkspaceRoot) -> Path:
    path = root.path / ".git"
    if path.is_symlink() or not path.is_dir():
        raise _error("git_repository_unsupported")
    for name in ("HEAD", "config", "objects", "refs"):
        item = path / name
        if item.is_symlink() or not item.exists():
            raise _error("git_repository_unsafe")
    if (path / "objects" / "info" / "alternates").exists() or (path / "info" / "grafts").exists():
        raise _error("git_repository_unsupported")
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        if (path / name).exists():
            raise _error("git_operation_in_progress")
    return path


def _repo(root: WorkspaceRoot) -> tuple[Repo, Path, bytes, bytes]:
    git_dir = _git_dir(root)
    try:
        repo = Repo(str(root.path))
        chain, head = repo.refs.follow(b"HEAD")
    except Exception:
        raise _error("git_repository_unavailable") from None
    if (
        repo.bare
        or len(chain) != 2
        or chain[0] != b"HEAD"
        or not chain[-1].startswith(b"refs/heads/")
    ):
        raise _error("git_repository_unsupported")
    if (
        head is None
        or len(head) != 40
        or os.fsencode(repo.path).rstrip(b"/") != os.fsencode(str(root.path))
    ):
        raise _error("git_repository_unsupported")
    config = (git_dir / "config").read_text(encoding="utf-8", errors="strict")
    section = ""
    unsupported_config = False
    for raw_line in config.splitlines():
        line = raw_line.strip().casefold()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].split('"', 1)[0].strip()
            if section.startswith(("extensions", "include", "includeif")):
                unsupported_config = True
            continue
        key, separator, value = line.partition("=")
        if not separator:
            unsupported_config = True
            continue
        if (
            section == "core" and key.strip() == "repositoryformatversion" and value.strip() != "0"
        ) or key.strip() in {"extensions.objectformat", "objectformat"}:
            unsupported_config = True
    if unsupported_config:
        raise _error("git_repository_unsupported")
    direct_ref = git_dir / chain[-1].decode("ascii")
    if direct_ref.is_symlink() or not direct_ref.is_file():
        raise _error("git_repository_unsafe")
    return repo, git_dir, chain[-1], head


def _index(repo: Repo, git_dir: Path) -> tuple[Index, str]:
    path = Path(repo.index_path())
    if path.is_symlink() or not path.is_file():
        raise _error("git_index_unsupported")
    raw = path.read_bytes()
    if (
        len(raw) < 32
        or raw[:4] != b"DIRC"
        or raw[4:8] not in {b"\x00\x00\x00\x02", b"\x00\x00\x00\x03"}
    ):
        raise _error("git_index_unsupported")
    try:
        index = Index(path)
    except Exception:
        raise _error("git_index_unsupported") from None
    if index.has_conflicts() or index.is_sparse() or getattr(index, "_extensions", ()):
        raise _error("git_index_unsupported")
    return index, hashlib.sha256(raw).hexdigest()


def _tree_entry(repo: Repo, tree: Tree, parts: list[bytes]) -> tuple[int, bytes]:
    current = tree
    for offset, part in enumerate(parts):
        try:
            mode, sha = current[part]
        except KeyError:
            raise _error("git_head_path_missing") from None
        if offset == len(parts) - 1:
            return mode, sha
        if stat.S_ISDIR(mode):
            item = repo.object_store[sha]
            if not isinstance(item, Tree):
                raise _error("git_tree_invalid")
            current = item
        else:
            raise _error("git_head_path_invalid")
    raise _error("git_head_path_invalid")


def _index_entry(index: Index, path: bytes) -> IndexEntry | None:
    try:
        value = index[path]
    except KeyError:
        return None
    return value if isinstance(value, IndexEntry) else None


def _read_worktree(root: WorkspaceRoot, path: str, expected_mode: int) -> bytes:
    if _denied(tuple(path.split("/"))):
        raise _error("sensitive_path_denied")
    value = root.resolve(path, allow_directory=False)
    try:
        metadata = value.stat()
        mode = stat.S_IFMT(metadata.st_mode) | stat.S_IMODE(metadata.st_mode)
        raw = value.read_bytes()
    except OSError:
        raise _error("workspace_read_failed") from None
    if mode != expected_mode or len(raw) > 65_536 or b"\x00" in raw:
        raise _error("git_worktree_unsupported")
    return raw


def prepare(root: WorkspaceRoot, candidates: list[dict[str, str]]) -> LocalPreparation:
    """Verify exact current paths and produce a complete, bounded immutable preview."""
    repo, git_dir, branch, head = _repo(root)
    index, index_fingerprint = _index(repo, git_dir)
    try:
        base = repo.object_store[head]
        if not isinstance(base, Commit):
            raise _error("git_head_invalid")
        tree = repo.object_store[base.tree]
        if not isinstance(tree, Tree):
            raise _error("git_head_invalid")
    except KeyError:
        raise _error("git_head_invalid") from None
    prepared: list[PreparedPath] = []
    diffs: list[str] = []
    for item in sorted(candidates, key=lambda value: value["path"].encode("utf-8")):
        path = item["path"]
        parts = path.encode("utf-8").split(b"/")
        mode, old_blob_id = _tree_entry(repo, tree, parts)
        if mode not in _REGULAR_MODES:
            raise _error("git_head_path_unsupported")
        entry = _index_entry(index, path.encode("utf-8"))
        if (
            entry is None
            or entry.sha != old_blob_id
            or entry.mode != mode
            or entry.stage().value != 0
        ):
            raise _error("git_index_target_dirty")
        old_blob = repo.object_store[old_blob_id]
        if not isinstance(old_blob, Blob):
            raise _error("git_head_path_invalid")
        old_bytes = old_blob.data
        if hashlib.sha256(old_bytes).hexdigest() != item["preimage_sha256"]:
            raise _error("git_preexisting_target_dirty")
        current = _read_worktree(root, path, mode)
        if hashlib.sha256(current).hexdigest() != item["candidate_sha256"]:
            raise _error("git_stale_worktree")
        diff = "".join(
            difflib.unified_diff(
                old_bytes.decode("utf-8").splitlines(keepends=True),
                current.decode("utf-8").splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        diffs.append(diff)
        blob = Blob.from_string(current)
        prepared.append(
            PreparedPath(
                path,
                item["preimage_sha256"],
                item["candidate_sha256"],
                mode,
                _hex(old_blob_id),
                _hex(blob.id),
            )
        )
    diff_text = "".join(diffs)
    if not prepared or len(diff_text.encode("utf-8")) > _MAX_DIFF_BYTES:
        raise _error("git_diff_preview_too_large")
    return LocalPreparation(
        repository_key=hashlib.sha256(str(root.path).encode("utf-8")).hexdigest(),
        branch_ref=branch.decode("ascii"),
        head_sha=_hex(head),
        index_fingerprint=index_fingerprint,
        paths=tuple(prepared),
        preview={
            "diff": diff_text,
            "diff_sha256": hashlib.sha256(diff_text.encode()).hexdigest(),
            "path_count": len(prepared),
            "diff_truncated": False,
        },
        tree_id=_hex(base.tree),
    )


def _replace_tree(
    repo: Repo,
    tree: Tree,
    replacements: dict[tuple[bytes, ...], tuple[int, bytes]],
    prefix: tuple[bytes, ...] = (),
    *,
    persist: bool = True,
) -> bytes:
    result = Tree()
    names = {name for name, _, _ in tree.iteritems()}
    child_names = {path[len(prefix)] for path in replacements if len(path) > len(prefix)}
    for name in sorted(names | child_names):
        direct = replacements.get(prefix + (name,))
        if direct is not None:
            result.add(name, direct[0], direct[1])
            continue
        mode, sha = tree[name]
        child_paths = [
            path
            for path in replacements
            if len(path) > len(prefix) + 1 and path[: len(prefix) + 1] == prefix + (name,)
        ]
        if child_paths:
            child = repo.object_store[sha]
            if not isinstance(child, Tree):
                raise _error("git_tree_invalid")
            sha = _replace_tree(repo, child, replacements, prefix + (name,), persist=persist)
        result.add(name, mode, sha)
    if persist:
        repo.object_store.add_object(result)
    return result.id


def apply(
    root: WorkspaceRoot,
    paths: list[dict[str, object]],
    *,
    expected_head: str,
    expected_index: str,
    branch_ref: str,
    message: str,
    identity: str,
    timestamp: datetime,
    expected_commit: str,
) -> str:
    """Create exactly one object/tree and CAS the prepared direct branch ref."""
    repo, git_dir, branch, head = _repo(root)
    if branch.decode() != branch_ref:
        raise _error("git_stale_branch")
    if _hex(head) == expected_commit:
        index, _ = _index(repo, git_dir)
        recovered: dict[tuple[bytes, ...], tuple[int, bytes]] = {}
        for item in paths:
            path = str(item["path"])
            mode = int(item["mode"])
            raw = _read_worktree(root, path, mode)
            if hashlib.sha256(raw).hexdigest() != str(item["candidate_sha256"]):
                raise _error("git_stale_worktree")
            candidate_id = str(item["candidate_blob_id"]).encode("ascii")
            candidate = repo.object_store[candidate_id]
            if not isinstance(candidate, Blob) or candidate.data != raw:
                raise _error("git_commit_recovery_invalid")
            recovered[tuple(path.encode().split(b"/"))] = (mode, candidate_id)
        _write_index_entries(root, index, recovered)
        return expected_commit
    if _hex(head) != expected_head:
        raise _error("git_stale_head")
    index, fingerprint = _index(repo, git_dir)
    if fingerprint != expected_index:
        raise _error("git_stale_index")
    base = repo.object_store[head]
    if not isinstance(base, Commit):
        raise _error("git_head_invalid")
    tree = repo.object_store[base.tree]
    if not isinstance(tree, Tree):
        raise _error("git_head_invalid")
    replacements: dict[tuple[bytes, ...], tuple[int, bytes]] = {}
    for item in paths:
        path = str(item["path"])
        mode = int(item["mode"])
        old_mode, old_blob_id = _tree_entry(repo, tree, path.encode().split(b"/"))
        if old_mode != mode or _hex(old_blob_id) != str(item["head_blob_id"]):
            raise _error("git_stale_path")
        entry = _index_entry(index, path.encode())
        if (
            entry is None
            or entry.sha != old_blob_id
            or entry.mode != mode
            or entry.stage().value != 0
        ):
            raise _error("git_stale_index")
        raw = _read_worktree(root, path, mode)
        if hashlib.sha256(raw).hexdigest() != str(item["candidate_sha256"]):
            raise _error("git_stale_worktree")
        blob = Blob.from_string(raw)
        repo.object_store.add_object(blob)
        replacements[tuple(path.encode().split(b"/"))] = (mode, blob.id)
    new_tree = _replace_tree(repo, tree, replacements)
    commit = Commit()
    commit.tree = new_tree
    commit.parents = [head]
    commit.author = identity.encode()
    commit.committer = identity.encode()
    commit.message = message.encode()
    commit.author_time = commit.commit_time = int(timestamp.timestamp())
    commit.author_timezone = commit.commit_timezone = 0
    repo.object_store.add_object(commit)
    if _hex(commit.id) != expected_commit:
        raise _error("git_commit_identity_mismatch")
    if not repo.refs.set_if_equals(branch, head, commit.id):
        raise _error("git_stale_head")
    _write_index_entries(root, index, replacements)
    return _hex(commit.id)


def _write_index_entries(
    root: WorkspaceRoot,
    index: Index,
    replacements: dict[tuple[bytes, ...], tuple[int, bytes]],
) -> None:
    """Rewrite only accepted entries while preserving all unrelated index entries."""
    for path, (mode, sha) in replacements.items():
        relative = b"/".join(path)
        working = root.resolve(relative.decode(), allow_directory=False).stat()
        index[relative] = IndexEntry(
            (int(working.st_ctime), 0),
            (int(working.st_mtime), 0),
            working.st_dev,
            working.st_ino,
            mode,
            working.st_uid,
            working.st_gid,
            working.st_size,
            sha,
        )
    index.write()


def expected_commit_sha(
    root: WorkspaceRoot,
    preparation: LocalPreparation,
    *,
    message: str,
    identity: str,
    timestamp: datetime,
) -> str:
    """Serialize the exact commit in memory, without writing an object or ref during prepare."""
    repo, _, _, head = _repo(root)
    base = repo.object_store[head]
    if not isinstance(base, Commit):
        raise _error("git_head_invalid")
    tree = repo.object_store[base.tree]
    if not isinstance(tree, Tree):
        raise _error("git_head_invalid")
    replacements = {
        tuple(item.path.encode().split(b"/")): (
            item.mode,
            item.candidate_blob_id.encode("ascii"),
        )
        for item in preparation.paths
    }
    new_tree = _replace_tree(repo, tree, replacements, persist=False)
    commit = Commit()
    commit.tree = new_tree
    commit.parents = [head]
    commit.author = identity.encode()
    commit.committer = identity.encode()
    commit.message = message.encode()
    commit.author_time = commit.commit_time = int(timestamp.timestamp())
    commit.author_timezone = commit.commit_timezone = 0
    return _hex(commit.id)
