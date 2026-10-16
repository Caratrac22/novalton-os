"""Server-owned static verification orchestration; all execution stays in I-044A."""

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novalton_api.infrastructure.verification_sandbox import (
    VerificationSandboxAdapter,
    VerificationSandboxError,
)


@dataclass(frozen=True)
class CommandDefinition:
    id: str = "verify.backend_syntax"
    version: int = 1
    permission: str = "verify.backend_syntax"
    policy_action: str = "tool.verify.backend_syntax"
    sandbox_operation: str = "verify"
    timeout_seconds: int = 15
    persisted_max_bytes: int = 4096
    side_effect_class: str = "READ_ONLY"


BACKEND_SYNTAX = CommandDefinition()
MAX_VERIFICATIONS = 2
WORKSPACE = Path("/srv/novalton/workspace")


class Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(pattern=r"^[A-Za-z0-9_./-]{1,200}$")
    code: Literal["python_syntax_invalid"]


class SyntaxResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    state: Literal["passed", "failed"]
    checked_files: int = Field(default=0, ge=0, le=4096)
    failed_files: int = Field(default=0, ge=0, le=4096)
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=4)
    truncated: bool = False
    exit_code: int | None = Field(ge=0, le=1)
    failure_code: (
        Literal[
            "verification_source_missing",
            "verification_source_empty",
            "verification_source_type",
            "verification_source_bound",
            "verification_unavailable",
            "verification_timeout",
        ]
        | None
    ) = None


def protected_state(root: Path) -> str:
    """Fingerprint all names/types/metadata without reading secrets or following links.

    Content containment is OS-enforced by the immutable snapshot. This detects
    concurrent live changes, including excluded files and Git index/objects;
    mtime and ctime are included, atime is deliberately excluded.
    """
    digest = hashlib.sha256()
    if (root / ".git").exists() and not (root / ".git").is_dir():
        raise VerificationSandboxError("verification_git_directory_required")
    count = 0
    for directory, names, files in os.walk(root, followlinks=False):
        names.sort()
        for name in [".", *sorted([*names, *files])]:
            path = Path(directory) if name == "." else Path(directory) / name
            info = path.lstat()
            count += 1
            if count > 100_000:
                raise VerificationSandboxError("workspace_integrity_bound")
            entry = (
                path.relative_to(root).as_posix(),
                info.st_mode,
                info.st_uid,
                info.st_gid,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
                info.st_ino,
                os.readlink(path) if stat.S_ISLNK(info.st_mode) else None,
            )
            digest.update(json.dumps(entry, separators=(",", ":")).encode())
            digest.update(b"\0")
    return digest.hexdigest()


def execute(root: Path) -> tuple[dict, dict]:
    """One immutable definition, no retries, no caller-controlled process fields."""
    if root != WORKSPACE or root.is_symlink():
        raise VerificationSandboxError("verification_workspace_not_bound")
    before = protected_state(root)
    try:
        result = VerificationSandboxAdapter(root).verify()
    finally:
        if protected_state(root) != before:
            raise VerificationSandboxError("unexpected_workspace_mutation")
    if (
        result.stale_source
        or not all(
            (
                result.population_empty,
                result.scratch_destroyed,
                result.snapshot_destroyed,
            )
        )
        or result.state != "passed"
    ):
        raise VerificationSandboxError("verification_sandbox_failed")
    parsed = SyntaxResult.model_validate(result.verification)
    failed = parsed.failure_code is not None
    if (
        parsed.failed_files > parsed.checked_files
        or (parsed.state == "passed") != (parsed.failed_files == 0 and not failed)
        or (
            not failed
            and (
                parsed.checked_files == 0
                or parsed.exit_code != (0 if parsed.state == "passed" else 1)
            )
        )
        or (failed and (parsed.checked_files != 0 or parsed.failed_files != 0))
        or len(parsed.diagnostics) != min(parsed.failed_files, 4)
        or parsed.truncated != (parsed.failed_files > 4)
        or any(
            ".." in item.path.split("/")
            or not (
                item.path == "redacted-path"
                or item.path.startswith(("apps/api/src/", "apps/api/tests/"))
            )
            for item in parsed.diagnostics
        )
    ):
        raise VerificationSandboxError("verification_result_invalid")
    if parsed.failure_code is not None:
        raise VerificationSandboxError(parsed.failure_code)
    metadata = {
        "command_id": BACKEND_SYNTAX.id,
        "command_version": BACKEND_SYNTAX.version,
        "parameters": {},
        "command_fingerprint": hashlib.sha256(b"verify.backend_syntax:1:{}").hexdigest(),
        "sandbox_run_id": result.run_id,
        "source_digest": result.source_digest,
        "workspace_integrity": "unchanged",
        "verification": parsed.model_dump(),
        "authority": "UNTRUSTED_DATA",
    }
    if len(json.dumps(metadata).encode()) > BACKEND_SYNTAX.persisted_max_bytes:
        raise VerificationSandboxError("verification_result_bound")
    return metadata, metadata
