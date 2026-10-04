"""Closed-world client for the independently supervised verification sandbox."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import stat
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

_ENDPOINT: Final = "/run/novalton-verification/control.sock"
_DEFINITION: Final = "repository-probe-v1"
_FOUNDATION_INPUT_SHA256: Final = "5e523e94210add1045c0dbe76f52899bfd41e1e0616fcb7fdd7d9b7da59340eb"
_I044A_INPUT_SHA256: Final = "870c52ee31debd1fd4b4805700a74992c9ac0bca721eb6d95d066bf1f594adf1"
_MAX_REQUEST_BYTES: Final = 1024
_MAX_RESPONSE_BYTES: Final = 8192
_MAX_FILES: Final = 4096
_MAX_FILE_BYTES: Final = 2 * 1024 * 1024
_MAX_SOURCE_BYTES: Final = 32 * 1024 * 1024
_RUN_ID: Final = re.compile(r"[0-9a-f]{32}\Z")
_CAPABILITY: Final = re.compile(r"[0-9a-f]{64}\Z")
_ERROR_CODE: Final = re.compile(r"[a-z0-9_]{1,64}\Z")
_PROBE_CHECKS: Final = frozenset(
    {
        "caps_empty",
        "clone3_newuser_denied",
        "clone3_ordinary_seccomp_denied",
        "clone3_namespaces_denied",
        "clone_newnet_denied",
        "clone_newns_denied",
        "clone_newuser_denied",
        "clone_ordinary_allowed",
        "clone_namespaces_denied",
        "core_disabled",
        "descendants_started",
        "docker_absent",
        "dotenv_absent",
        "environment_minimal",
        "fds_clean",
        "git_absent",
        "home_absent",
        "host_api_denied",
        "host_filesystem_absent",
        "loopback_only",
        "mount_escape_absent",
        "network_denied",
        "no_new_privileges",
        "no_pty",
        "outside_fixture_absent",
        "postgres_denied",
        "private_pid",
        "provider_secrets_absent",
        "python_313",
        "scratch_bounded",
        "scratch_writable",
        "seccomp_active",
        "seccomp_filter_present",
        "source_readonly",
        "ssh_agent_absent",
        "stdin_closed",
        "user_namespace_private",
    }
)
_EXCLUDED_NAMES: Final = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "coverage",
        "dist",
        "node_modules",
    }
)


class VerificationSandboxError(RuntimeError):
    """A deterministic, non-sensitive verification sandbox failure."""


@dataclass(frozen=True)
class VerificationResult:
    """Bounded result metadata from one fixed repository containment probe."""

    run_id: str
    state: str
    source_digest: str
    stale_source: bool
    population_empty: bool
    scratch_destroyed: bool
    snapshot_destroyed: bool
    output_truncated: bool
    checks: dict[str, bool]
    failure_code: str | None = None


def _excluded(relative: PurePosixPath) -> bool:
    return any(part in _EXCLUDED_NAMES or part.startswith(".env") for part in relative.parts)


def _regular_files(root: Path) -> list[tuple[PurePosixPath, Path]]:
    files: list[tuple[PurePosixPath, Path]] = []
    entries = 0
    total = 0
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        base = Path(directory)
        kept: list[str] = []
        for name in sorted(names):
            relative = PurePosixPath((base / name).relative_to(root).as_posix())
            path = base / name
            if _excluded(relative):
                continue
            if path.is_symlink():
                raise VerificationSandboxError("source_symlink_denied")
            kept.append(name)
            entries += 1
            if entries > _MAX_FILES:
                raise VerificationSandboxError("source_bound_exceeded")
        names[:] = kept
        for name in sorted(filenames):
            path = base / name
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if _excluded(relative):
                continue
            try:
                info = path.lstat()
            except OSError:
                raise VerificationSandboxError("source_unavailable") from None
            if stat.S_ISLNK(info.st_mode):
                raise VerificationSandboxError("source_symlink_denied")
            if not stat.S_ISREG(info.st_mode):
                raise VerificationSandboxError("source_special_file_denied")
            if info.st_size > _MAX_FILE_BYTES:
                raise VerificationSandboxError("source_file_too_large")
            entries += 1
            total += info.st_size
            if entries > _MAX_FILES or total > _MAX_SOURCE_BYTES:
                raise VerificationSandboxError("source_bound_exceeded")
            files.append((relative, path))
    return sorted(files, key=lambda item: item[0].as_posix().encode())


def _digest_files(files: list[tuple[PurePosixPath, Path]]) -> str:
    digest = hashlib.sha256()
    for relative, path in files:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            with os.fdopen(descriptor, "rb", closefd=True) as reader:
                data = reader.read(_MAX_FILE_BYTES + 1)
        except OSError:
            raise VerificationSandboxError("source_unavailable") from None
        if len(data) > _MAX_FILE_BYTES:
            raise VerificationSandboxError("source_file_too_large")
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(data)
    return digest.hexdigest()


def source_digest(root: Path) -> str:
    """Hash the admitted regular-file view without reading excluded content."""
    return _digest_files(_regular_files(root))


class VerificationSandboxAdapter:
    """Server-owned adapter with no caller-controlled execution authority.

    The workspace root is bound once by trusted server configuration. The only
    executable action is the installed ``repository-probe-v1`` definition.
    """

    def __init__(self, workspace_root: Path) -> None:
        try:
            root = workspace_root.resolve(strict=True)
        except OSError:
            raise VerificationSandboxError("workspace_unavailable") from None
        if not root.is_dir() or root == Path("/"):
            raise VerificationSandboxError("workspace_invalid")
        self._workspace_root = root

    def _request(self, request: dict[str, str]) -> dict[str, Any]:
        encoded = json.dumps(request, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        if len(encoded) > _MAX_REQUEST_BYTES:
            raise VerificationSandboxError("request_bound")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(2)
                connection.connect(_ENDPOINT)
                connection.sendall(encoded)
                response = bytearray()
                while not response.endswith(b"\n"):
                    chunk = connection.recv(_MAX_RESPONSE_BYTES + 1 - len(response))
                    if not chunk:
                        raise VerificationSandboxError("empty_response")
                    response.extend(chunk)
                    if len(response) > _MAX_RESPONSE_BYTES:
                        raise VerificationSandboxError("response_bound")
        except VerificationSandboxError:
            raise
        except (OSError, TimeoutError):
            raise VerificationSandboxError("sandbox_unavailable") from None
        try:
            value = json.loads(response)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise VerificationSandboxError("invalid_response") from None
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise VerificationSandboxError("invalid_response")
        if isinstance(value.get("error"), str):
            raise VerificationSandboxError(value["error"])
        return value

    def health(self) -> dict[str, Any]:
        """Return safe readiness metadata after pin validation."""
        value = self._request({"op": "health"})
        if (
            value.get("state") != "ready"
            or value.get("definition") != _DEFINITION
            or value.get("foundation_input_sha256") != _FOUNDATION_INPUT_SHA256
            or value.get("i044a_input_sha256") != _I044A_INPUT_SHA256
            or not isinstance(value.get("foundation_installed_manifest_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value["foundation_installed_manifest_sha256"]) is None
            or not isinstance(value.get("installed_manifest_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value["installed_manifest_sha256"]) is None
            or value.get("db_mode") is not False
        ):
            raise VerificationSandboxError("sandbox_definition_mismatch")
        return value

    def verify(self) -> VerificationResult:
        """Snapshot the bound workspace and run the single installed probe."""
        self.health()
        prepared = self._request({"op": "prepare"})
        capability = prepared.get("capability")
        snapshot_digest = prepared.get("source_digest")
        if (
            prepared.get("state") != "prepared"
            or not isinstance(capability, str)
            or _CAPABILITY.fullmatch(capability) is None
            or not isinstance(snapshot_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", snapshot_digest) is None
        ):
            raise VerificationSandboxError("invalid_response")
        accepted = self._request({"op": "verify", "capability": capability})
        run_id = accepted.get("run_id")
        if (
            accepted.get("state") != "accepted"
            or not isinstance(run_id, str)
            or _RUN_ID.fullmatch(run_id) is None
        ):
            raise VerificationSandboxError("invalid_response")
        deadline = time.monotonic() + 15
        while True:
            value = self._request({"op": "result", "run_id": run_id})
            if value.get("state") != "running":
                break
            if time.monotonic() >= deadline:
                self._request({"op": "cancel", "run_id": run_id})
                raise VerificationSandboxError("adapter_timeout")
            time.sleep(0.05)
        try:
            stale = source_digest(self._workspace_root) != snapshot_digest
        except VerificationSandboxError:
            stale = True
        checks = value.get("checks", {})
        if not isinstance(checks, dict) or (
            checks
            and (
                set(checks) != _PROBE_CHECKS
                or not all(type(check) is bool for check in checks.values())
            )
        ):
            raise VerificationSandboxError("invalid_response")
        state = value.get("state") if isinstance(value.get("state"), str) else "failed"
        if value.get("source_digest") != snapshot_digest or (
            state == "passed" and (set(checks) != _PROBE_CHECKS or not all(checks.values()))
        ):
            raise VerificationSandboxError("invalid_response")
        if stale:
            state = "stale_source"
        failure_code = value.get("failure_code")
        if failure_code is not None and (
            not isinstance(failure_code, str) or _ERROR_CODE.fullmatch(failure_code) is None
        ):
            raise VerificationSandboxError("invalid_response")
        return VerificationResult(
            run_id=run_id,
            state=state,
            source_digest=snapshot_digest,
            stale_source=stale,
            population_empty=value.get("population_empty") is True,
            scratch_destroyed=value.get("scratch_destroyed") is True,
            snapshot_destroyed=value.get("snapshot_destroyed") is True,
            output_truncated=value.get("output_truncated") is True,
            checks=checks,
            failure_code=failure_code,
        )
