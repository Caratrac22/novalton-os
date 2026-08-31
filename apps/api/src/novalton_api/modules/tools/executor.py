"""Conservative read-only workspace executors with one approved root."""

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from pydantic import BaseModel

from novalton_api.infrastructure.providers.contracts import ExecutionTargetClass
from novalton_api.modules.policy.schemas import RiskLevel
from novalton_api.modules.tools.contracts import (
    SideEffectClass,
    ToolDefinition,
    WorkspaceListFilesInput,
    WorkspaceReadFileInput,
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


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    executor: Executor


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


def _registered(tool_id: str, description: str, executor: Executor) -> RegisteredTool:
    return RegisteredTool(
        definition=ToolDefinition(
            tool_id=tool_id,
            description=description,
            input_schema=executor.input_model.model_json_schema(),
            output_max_bytes=131_072,
            risk_class=RiskLevel.LOW,
            execution_locality=ExecutionTargetClass.LOCAL,
            required_permission=tool_id,
            policy_action=f"tool.{tool_id}",
            side_effect_class=SideEffectClass.READ_ONLY,
        ),
        executor=executor,
    )


TRUSTED_TOOL_REGISTRY = ToolRegistry(
    (
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
    )
)
