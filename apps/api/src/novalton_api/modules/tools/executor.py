"""Conservative read-only workspace executors with one approved root."""

import hashlib
import os
import secrets
import stat
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from novalton_api.infrastructure.providers.contracts import ExecutionTargetClass
from novalton_api.modules.policy.schemas import RiskLevel
from novalton_api.modules.tools.contracts import (
    SideEffectClass,
    ToolDefinition,
    VerificationArguments,
    WorkspaceListFilesInput,
    WorkspaceReadFileInput,
    WorkspaceReplaceTextInput,
    WorkspaceSearchTextInput,
)

_DENIED_NAMES = {
    ".git",
    ".ssh",
    ".aws",
    ".gnupg",
    "credentials",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
}
_DENIED_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
_MAX_SCANNED_FILES = 1_000
_MAX_SEARCH_FILE_BYTES = 65_536
_MAX_SNIPPET_CHARACTERS = 300
_MAX_MUTATION_FILE_BYTES = 65_536
_MAX_DIFF_BYTES = 16_384


class ToolExecutionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _denied(parts: tuple[str, ...]) -> bool:
    for part in parts:
        lowered = part.casefold()
        if (
            lowered in _DENIED_NAMES
            or lowered.startswith(".env")
            or lowered.endswith(tuple(_DENIED_SUFFIXES))
            or "secret" in lowered
        ):
            return True
    return False


@dataclass(frozen=True)
class WorkspaceRoot:
    path: Path

    @classmethod
    def approved(cls, value: str | Path) -> "WorkspaceRoot":
        path = Path(value)
        if not path.is_absolute():
            raise ToolExecutionError("workspace_root_not_absolute")
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            raise ToolExecutionError("workspace_root_unavailable") from None
        if not resolved.is_dir():
            raise ToolExecutionError("workspace_root_not_directory")
        return cls(resolved)

    def resolve(self, relative: str, *, allow_directory: bool) -> Path:
        if "\\" in relative or relative.startswith("/"):
            raise ToolExecutionError("invalid_relative_path")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or any(part in {"..", ""} for part in pure.parts):
            raise ToolExecutionError("path_traversal_denied")
        if _denied(pure.parts):
            raise ToolExecutionError("sensitive_path_denied")
        candidate = self.path.joinpath(*pure.parts)
        current = self.path
        for part in pure.parts:
            current = current / part
            if current.is_symlink():
                raise ToolExecutionError("symlink_path_denied")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.path)
        except (OSError, ValueError):
            raise ToolExecutionError("outside_workspace_denied") from None
        if resolved.is_symlink():
            raise ToolExecutionError("symlink_path_denied")
        if allow_directory:
            if not resolved.is_dir():
                raise ToolExecutionError("directory_required")
        elif not resolved.is_file():
            raise ToolExecutionError("regular_file_required")
        return resolved

    def relative(self, path: Path) -> str:
        return path.relative_to(self.path).as_posix() or "."


class Executor(Protocol):
    input_model: type[BaseModel]

    def execute(
        self, root: WorkspaceRoot, data: BaseModel
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return transient evidence and safe durable result metadata."""


class ListFilesExecutor:
    input_model = WorkspaceListFilesInput

    def execute(
        self, root: WorkspaceRoot, data: BaseModel
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert isinstance(data, WorkspaceListFilesInput)
        directory = root.resolve(data.path, allow_directory=True)
        items: list[dict[str, Any]] = []
        truncated = False

        def visit(path: Path, depth: int) -> None:
            nonlocal truncated
            if truncated:
                return
            try:
                children = sorted(path.iterdir(), key=lambda item: item.name.casefold())
            except OSError:
                raise ToolExecutionError("workspace_read_failed") from None
            for child in children:
                relative = child.relative_to(root.path)
                if _denied(relative.parts) or child.is_symlink():
                    continue
                if len(items) >= data.max_results:
                    truncated = True
                    return
                if child.is_dir():
                    items.append({"path": relative.as_posix(), "type": "directory"})
                    if depth < data.max_depth:
                        visit(child, depth + 1)
                elif child.is_file():
                    try:
                        size = child.stat().st_size
                    except OSError:
                        continue
                    items.append({"path": relative.as_posix(), "type": "file", "size_bytes": size})

        visit(directory, 0)
        evidence = {"base_path": root.relative(directory), "items": items, "truncated": truncated}
        metadata = {
            "base_path": root.relative(directory),
            "result_count": len(items),
            "truncated": truncated,
        }
        return evidence, metadata


class ReadFileExecutor:
    input_model = WorkspaceReadFileInput

    def execute(
        self, root: WorkspaceRoot, data: BaseModel
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert isinstance(data, WorkspaceReadFileInput)
        path = root.resolve(data.path, allow_directory=False)
        try:
            with path.open("rb") as handle:
                raw = handle.read(data.max_bytes + 1)
        except OSError:
            raise ToolExecutionError("workspace_read_failed") from None
        truncated = len(raw) > data.max_bytes
        bounded = raw[: data.max_bytes]
        if b"\x00" in bounded:
            raise ToolExecutionError("binary_file_denied")
        try:
            text = bounded.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ToolExecutionError("non_utf8_file_denied") from None
        evidence = {
            "path": root.relative(path),
            "text": text,
            "bytes_returned": len(bounded),
            "truncated": truncated,
        }
        metadata = {
            "path": root.relative(path),
            "bytes_returned": len(bounded),
            "content_sha256": hashlib.sha256(bounded).hexdigest(),
            "truncated": truncated,
        }
        return evidence, metadata


class SearchTextExecutor:
    input_model = WorkspaceSearchTextInput

    def execute(
        self, root: WorkspaceRoot, data: BaseModel
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert isinstance(data, WorkspaceSearchTextInput)
        base = root.resolve(data.path, allow_directory=True)
        matches: list[dict[str, Any]] = []
        scanned = 0
        truncated = False
        for path in sorted(base.rglob("*"), key=lambda item: item.as_posix().casefold()):
            relative = path.relative_to(root.path)
            if _denied(relative.parts) or path.is_symlink() or not path.is_file():
                continue
            scanned += 1
            if scanned > _MAX_SCANNED_FILES:
                truncated = True
                break
            try:
                size = path.stat().st_size
                if size > _MAX_SEARCH_FILE_BYTES:
                    continue
                raw = path.read_bytes()
                if b"\x00" in raw:
                    continue
                text = raw.decode("utf-8", errors="strict")
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if data.query not in line:
                    continue
                matches.append(
                    {
                        "path": relative.as_posix(),
                        "line_number": line_number,
                        "snippet": line[:_MAX_SNIPPET_CHARACTERS],
                        "snippet_truncated": len(line) > _MAX_SNIPPET_CHARACTERS,
                    }
                )
                if len(matches) >= data.max_results:
                    truncated = True
                    break
            if truncated:
                break
        evidence = {"base_path": root.relative(base), "matches": matches, "truncated": truncated}
        metadata = {
            "base_path": root.relative(base),
            "query_sha256": hashlib.sha256(data.query.encode("utf-8")).hexdigest(),
            "scanned_file_count": min(scanned, _MAX_SCANNED_FILES),
            "result_count": len(matches),
            "truncated": truncated,
        }
        return evidence, metadata


@contextmanager
def _mutation_parent(root: WorkspaceRoot, relative: str):
    """Pin each directory before resolving its child; never follow a symlink."""
    pure = PurePosixPath(relative)
    if "\\" in relative or pure.is_absolute() or "\x00" in relative:
        raise ToolExecutionError("invalid_relative_path")
    if not pure.parts or ".." in pure.parts:
        raise ToolExecutionError("path_traversal_denied")
    if _denied(pure.parts):
        raise ToolExecutionError("sensitive_path_denied")
    descriptor = -1
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open("/", flags)
        for part in (*root.path.parts[1:], *pure.parts[:-1]):
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor, pure.name, pure.as_posix()
    except OSError:
        raise ToolExecutionError("workspace_mutation_failed") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _mutation_metadata(descriptor: int) -> os.stat_result:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        raise ToolExecutionError("workspace_file_type_denied")
    if info.st_uid != os.geteuid():
        raise ToolExecutionError("workspace_file_owner_denied")
    if info.st_mode & 0o7000:
        raise ToolExecutionError("workspace_privileged_mode_denied")
    # Replacing an inode would discard ACLs, labels and other security metadata.
    # Unsupported/failed inspection is also an error, never permission to proceed.
    if os.listxattr(descriptor):
        raise ToolExecutionError("workspace_file_attributes_denied")
    return info


def _check_mutation_parent(root: WorkspaceRoot, relative: str, parent: int) -> None:
    """Reject moved parents instead of reporting a mutation at a stale path.

    This is a fail-closed recheck, not a filesystem compare-and-swap against
    another same-UID writer racing the final rename.
    """
    try:
        with _mutation_parent(root, relative) as (current, _, _):
            original_info = os.fstat(parent)
            current_info = os.fstat(current)
            if (current_info.st_dev, current_info.st_ino) != (
                original_info.st_dev,
                original_info.st_ino,
            ):
                raise ToolExecutionError("workspace_parent_changed")
    except ToolExecutionError:
        raise ToolExecutionError("workspace_parent_changed") from None


def _mutation_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_mutation_file(parent: int, name: str) -> tuple[bytes, os.stat_result]:
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent
    )
    with os.fdopen(descriptor, "rb") as reader:
        original = _mutation_metadata(reader.fileno())
        if original.st_size > _MAX_MUTATION_FILE_BYTES:
            raise ToolExecutionError("oversized_file_denied")
        raw = reader.read(_MAX_MUTATION_FILE_BYTES + 1)
        if len(raw) > _MAX_MUTATION_FILE_BYTES:
            raise ToolExecutionError("oversized_file_denied")
        if _mutation_identity(_mutation_metadata(reader.fileno())) != _mutation_identity(original):
            raise ToolExecutionError("stale_preimage")
    return raw, original


class ReplaceTextExecutor:
    input_model = WorkspaceReplaceTextInput

    def prepare(
        self, root: WorkspaceRoot, data: WorkspaceReplaceTextInput
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with _mutation_parent(root, data.path) as (parent, name, relative):
            before, _ = _read_mutation_file(parent, name)
            _check_mutation_parent(root, relative, parent)
        path = root.path / relative
        if b"\x00" in before:
            raise ToolExecutionError("binary_file_denied")
        try:
            text = before.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ToolExecutionError("non_utf8_file_denied") from None
        matches = text.count(data.search)
        if matches != data.expected_matches:
            raise ToolExecutionError("replace_match_count_mismatch")
        candidate = text.replace(data.search, data.replacement)
        candidate_bytes = candidate.encode("utf-8")
        if len(candidate_bytes) > _MAX_MUTATION_FILE_BYTES:
            raise ToolExecutionError("oversized_candidate_denied")
        before_sha = hashlib.sha256(before).hexdigest()
        candidate_sha = hashlib.sha256(candidate_bytes).hexdigest()
        mutation_sha = hashlib.sha256(
            (root.relative(path) + "\0" + before_sha + "\0" + candidate_sha).encode()
        ).hexdigest()
        import difflib

        diff = "".join(
            difflib.unified_diff(
                text.splitlines(keepends=True),
                candidate.splitlines(keepends=True),
                fromfile=root.relative(path),
                tofile=root.relative(path),
            )
        )
        diff_bytes = diff.encode("utf-8")
        truncated = len(diff_bytes) > _MAX_DIFF_BYTES
        if truncated:
            raise ToolExecutionError("diff_preview_too_large")
        preview = diff_bytes[:_MAX_DIFF_BYTES].decode("utf-8", errors="replace")
        metadata = {
            "path": root.relative(path),
            "preimage_sha256": before_sha,
            "candidate_sha256": candidate_sha,
            "mutation_fingerprint": mutation_sha,
            "before_bytes": len(before),
            "after_bytes": len(candidate_bytes),
            "before_lines": text.count("\n") + (1 if text else 0),
            "after_lines": candidate.count("\n") + (1 if candidate else 0),
            "diff_preview": preview,
            "diff_truncated": truncated,
            "search": data.search,
            "replacement": data.replacement,
            "expected_matches": data.expected_matches,
        }
        return {
            "path": root.relative(path),
            "preview": preview,
            "diff_truncated": truncated,
        }, metadata

    def apply(
        self, root: WorkspaceRoot, data: WorkspaceReplaceTextInput, prepared: dict[str, Any]
    ) -> dict[str, Any]:
        with _mutation_parent(root, data.path) as (parent, name, relative):
            current, original = _read_mutation_file(parent, name)
            _check_mutation_parent(root, relative, parent)
            current_sha = hashlib.sha256(current).hexdigest()
            if current_sha == prepared["candidate_sha256"]:
                return {"path": relative, "already_applied": True}
            if current_sha != prepared["preimage_sha256"]:
                raise ToolExecutionError("stale_preimage")
            try:
                current_text = current.decode("utf-8", errors="strict")
                search = str(prepared["search"])
                replacement = str(prepared["replacement"])
                expected_matches = int(prepared["expected_matches"])
            except (UnicodeDecodeError, KeyError, TypeError, ValueError):
                raise ToolExecutionError("prepared_mutation_invalid") from None
            if current_text.count(search) != expected_matches:
                raise ToolExecutionError("stale_preimage")
            candidate = current_text.replace(search, replacement).encode("utf-8")
            if len(candidate) > _MAX_MUTATION_FILE_BYTES:
                raise ToolExecutionError("oversized_candidate_denied")
            candidate_sha = hashlib.sha256(candidate).hexdigest()
            mutation_sha = hashlib.sha256(
                (relative + "\0" + current_sha + "\0" + candidate_sha).encode()
            ).hexdigest()
            if candidate_sha != prepared.get("candidate_sha256") or mutation_sha != prepared.get(
                "mutation_fingerprint"
            ):
                raise ToolExecutionError("mutation_fingerprint_mismatch")
            temporary = ".novalton-i041-" + secrets.token_hex(16)
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=parent,
            )
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    # Reject inherited default ACLs/security labels too: chmod
                    # must not silently erase restrictions on the replacement.
                    _mutation_metadata(handle.fileno())
                    handle.write(candidate)
                    handle.flush()
                    os.fchown(handle.fileno(), -1, original.st_gid)
                    os.fchmod(handle.fileno(), stat.S_IMODE(original.st_mode))
                    replacement = _mutation_metadata(handle.fileno())
                    if (replacement.st_uid, replacement.st_gid, replacement.st_mode) != (
                        original.st_uid,
                        original.st_gid,
                        original.st_mode,
                    ):
                        raise ToolExecutionError("workspace_file_metadata_mismatch")
                    os.fsync(handle.fileno())
                latest, identity = _read_mutation_file(parent, name)
                if latest != current or (
                    _mutation_identity(identity) != _mutation_identity(original)
                ):
                    raise ToolExecutionError("stale_preimage")
                _check_mutation_parent(root, relative, parent)
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=parent)
            return {"path": relative, "already_applied": False}


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    executor: Executor


class VerificationExecutor:
    input_model = VerificationArguments

    def execute(self, root: WorkspaceRoot, data: BaseModel) -> tuple[dict, dict]:
        from novalton_api.infrastructure.verification_sandbox import VerificationSandboxError
        from novalton_api.modules.tools.verification import execute

        assert isinstance(data, VerificationArguments)
        try:
            return execute(root.path)
        except VerificationSandboxError as error:
            # Only closed server errors cross this boundary. Never persist a
            # raw worker error, process output, path or connection exception.
            allowed = {
                "unexpected_workspace_mutation",
                "verification_workspace_not_bound",
                "snapshot_workspace_mismatch",
                "stale_source",
                "adapter_timeout",
                "sandbox_unavailable",
                "verification_sandbox_failed",
                "verification_timeout",
                "verification_source_missing",
                "verification_source_empty",
                "verification_source_type",
                "verification_source_bound",
            }
            code = str(error) if str(error) in allowed else "verification_unavailable"
            raise ToolExecutionError(code) from None
        except (OSError, ValidationError):
            raise ToolExecutionError("verification_unavailable") from None


class ToolRegistry:
    """Exact lookup of three immutable, server-owned read-only tools."""

    def __init__(self, tools: tuple[RegisteredTool, ...]) -> None:
        self._tools = {tool.definition.tool_id: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("duplicate trusted tool id")

    def get(self, tool_id: str) -> RegisteredTool | None:
        return self._tools.get(tool_id)

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._tools[key].definition for key in sorted(self._tools))


def _registered(
    tool_id: str,
    description: str,
    executor: Executor,
    *,
    side_effect: SideEffectClass = SideEffectClass.READ_ONLY,
    risk: RiskLevel = RiskLevel.LOW,
    output_max_bytes: int = 131_072,
) -> RegisteredTool:
    return RegisteredTool(
        definition=ToolDefinition(
            tool_id=tool_id,
            description=description,
            input_schema=executor.input_model.model_json_schema(),
            output_max_bytes=output_max_bytes,
            risk_class=risk,
            execution_locality=ExecutionTargetClass.LOCAL,
            required_permission=tool_id,
            policy_action=f"tool.{tool_id}",
            side_effect_class=side_effect,
        ),
        executor=executor,
    )


TRUSTED_TOOL_REGISTRY = ToolRegistry(
    (
        _registered(
            "verify.backend_syntax",
            "Check Python syntax in fixed backend roots inside the verification sandbox; "
            "no tests are executed.",
            VerificationExecutor(),
            output_max_bytes=4096,
        ),
        _registered(
            "workspace.list_files", "List bounded safe workspace paths.", ListFilesExecutor()
        ),
        _registered(
            "workspace.read_file", "Read bounded UTF-8 workspace text.", ReadFileExecutor()
        ),
        _registered(
            "workspace.search_text",
            "Search bounded workspace text literally.",
            SearchTextExecutor(),
        ),
        _registered(
            "workspace.replace_text",
            "Replace exact bounded text in one UTF-8 file.",
            ReplaceTextExecutor(),
            side_effect=SideEffectClass.MUTATION,
            risk=RiskLevel.MEDIUM,
        ),
    )
)
