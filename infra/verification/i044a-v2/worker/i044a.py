"""I-044A source-snapshot extension of the accepted I-044B worker."""

from __future__ import annotations

import array
import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import selectors
import shutil
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path, PurePosixPath

RELEASE = Path(__file__).resolve().parent.parent
FOUNDATION_DIGEST = "6643fdf075190c785de92ee28e0776915297640208fd091b64045313fe16bd7c"
CAPABILITY = re.compile(r"[0-9a-f]{64}\Z")
SNAPSHOT_SOURCE = Path("/run/novalton-verification/source")
CAPABILITY_LIFETIME = 2.0
MAX_FILES = 4096
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 32 * 1024 * 1024
EXCLUDED = {
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
CHECKS = {
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

spec = importlib.util.spec_from_file_location(
    "i044b_worker", RELEASE / "worker/worker.py"
)
foundation = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(foundation)


def decode(data: bytes, descriptor_count: int) -> dict[str, str]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result

    if len(data) > 1024:
        raise ValueError("request_bound")
    value = json.loads(data, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise TypeError("request_shape")
    operation = value.get("op")
    fields = {
        "health": {"op"},
        "diagnostic": {"op"},
        "prepare": {"op"},
        "verify": {"op", "capability"},
        "result": {"op", "run_id"},
        "cancel": {"op", "run_id"},
        "cleanup": {"op", "run_id"},
    }
    if (
        not isinstance(operation, str)
        or operation not in fields
        or set(value) != fields[operation]
    ):
        raise ValueError("request_shape")
    if "run_id" in value and (
        not isinstance(value["run_id"], str)
        or foundation.RUN_ID.fullmatch(value["run_id"]) is None
    ):
        raise ValueError("run_identity")
    if "capability" in value and (
        not isinstance(value["capability"], str)
        or CAPABILITY.fullmatch(value["capability"]) is None
    ):
        raise ValueError("capability_identity")
    if descriptor_count != 0:
        raise ValueError("descriptor_shape")
    return value  # type: ignore[return-value]


def _sensitive(relative: PurePosixPath) -> bool:
    return any(part in EXCLUDED or part.startswith(".env") for part in relative.parts)


def _copy_directory(
    source_fd: int, destination: Path, prefix: PurePosixPath, budget: list[int]
) -> None:
    for name in sorted(os.listdir(source_fd), key=lambda value: value.encode()):
        if not name or name in {".", ".."} or "/" in name or "\x00" in name:
            raise foundation.WorkerFailure("snapshot_invalid")
        relative = prefix / name
        if _sensitive(relative):
            continue
        budget[0] += 1
        if budget[0] > MAX_FILES:
            raise foundation.WorkerFailure("snapshot_bound_exceeded")
        info = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        target = destination / name
        if stat.S_ISDIR(info.st_mode):
            target.mkdir(mode=0o700)
            child = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=source_fd,
            )
            try:
                _copy_directory(child, target, relative, budget)
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            if info.st_size > MAX_FILE_BYTES:
                raise foundation.WorkerFailure("snapshot_file_too_large")
            source = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=source_fd
            )
            try:
                with (
                    os.fdopen(source, "rb", closefd=True) as reader,
                    target.open("xb") as writer,
                ):
                    copied = 0
                    while chunk := reader.read(64 * 1024):
                        copied += len(chunk)
                        if copied > MAX_FILE_BYTES:
                            raise foundation.WorkerFailure("snapshot_file_too_large")
                        budget[1] += len(chunk)
                        if budget[1] > MAX_SOURCE_BYTES:
                            raise foundation.WorkerFailure("snapshot_bound_exceeded")
                        writer.write(chunk)
            except Exception:
                if target.exists():
                    target.unlink()
                raise
        else:
            raise foundation.WorkerFailure("snapshot_special_file")


def _snapshot_digest(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix().encode(),
    )
    for path in files:
        data = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(data)
    return digest.hexdigest()


def destroy_snapshot(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        for item in path.rglob("*"):
            if item.is_dir():
                item.chmod(0o700)
        path.chmod(0o700)
        shutil.rmtree(path)
        return not path.exists()
    except OSError:
        return False


def stage_snapshot(identity: str) -> tuple[Path, str]:
    destination = foundation.STORAGE / ("snapshot-" + identity)
    source_fd = -1
    try:
        source_fd = os.open(
            SNAPSHOT_SOURCE,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        info = os.fstat(source_fd)
        if not stat.S_ISDIR(info.st_mode):
            raise foundation.WorkerFailure("snapshot_not_directory")
        destination.mkdir(mode=0o700)
        budget = [0, 0]
        _copy_directory(source_fd, destination, PurePosixPath(), budget)
        if budget[0] == 0:
            raise foundation.WorkerFailure("snapshot_empty")
        snapshot_digest = _snapshot_digest(destination)
        for item in destination.rglob("*"):
            item.chmod(0o500 if item.is_dir() else 0o400)
        destination.chmod(0o500)
        return destination, snapshot_digest
    except Exception:
        destroy_snapshot(destination)
        raise
    finally:
        if source_fd >= 0:
            os.close(source_fd)


class Worker(foundation.Worker):
    def __init__(self, cgroup: Path, digest: str):
        super().__init__(cgroup, digest)
        self.pending: dict[str, object] | None = None
        snapshots_ok = True
        for path in foundation.STORAGE.glob("snapshot-*"):
            snapshots_ok &= destroy_snapshot(path)
        if self.recent is not None and self.recent.get("state") == "reconciled":
            self.recent["snapshot_destroyed"] = snapshots_ok
            foundation.write_state(foundation.STORAGE / "recent.json", self.recent)
        self.blocked |= not snapshots_ok

    def _discard_pending(self) -> None:
        if self.pending is not None:
            self.blocked |= not destroy_snapshot(self.pending["snapshot"])
            self.pending = None

    def request(self, value: dict[str, str], peer_pid: int) -> dict[str, object]:
        with self.lock:
            operation = value["op"]
            if self.pending is not None and time.monotonic() >= self.pending["expires"]:
                self._discard_pending()
            if operation == "health":
                return {
                    "state": "blocked" if self.blocked else "ready",
                    "active": self.active is not None or self.pending is not None,
                    "definition": "repository-probe-v1",
                    "release_digest": self.digest,
                    "foundation_digest": FOUNDATION_DIGEST,
                    "reconciled": self.reconciled,
                    "db_mode": False,
                }
            if operation in {"diagnostic", "prepare"}:
                if self.blocked or self.active is not None or self.pending is not None:
                    return {"error": "unavailable" if self.blocked else "busy"}
                identity = uuid.uuid4().hex
                if operation == "prepare":
                    snapshot, source_digest = stage_snapshot(identity)
                    capability = secrets.token_hex(32)
                    self.pending = {
                        "capability": capability,
                        "expires": time.monotonic() + CAPABILITY_LIFETIME,
                        "peer_pid": peer_pid,
                        "snapshot": snapshot,
                        "source_digest": source_digest,
                        "run_id": identity,
                    }
                    return {
                        "capability": capability,
                        "source_digest": source_digest,
                        "state": "prepared",
                    }
                snapshot = None
                job = {
                    "run_id": identity,
                    "cancel": threading.Event(),
                    "kind": operation,
                    "snapshot": snapshot,
                    "source_digest": value.get("source_digest"),
                }
                foundation.write_state(
                    foundation.STORAGE / "current.json", {"run_id": identity}
                )
                self.active = job
                target = self.execute_probe if operation == "verify" else self.execute
                threading.Thread(target=target, args=(job,), daemon=True).start()
                return {"run_id": identity, "state": "accepted"}
            if operation == "verify":
                pending = self.pending
                if (
                    pending is None
                    or peer_pid != pending["peer_pid"]
                    or not hmac.compare_digest(value["capability"], pending["capability"])
                ):
                    return {"error": "invalid_capability"}
                self.pending = None
                job = {
                    "run_id": pending["run_id"],
                    "cancel": threading.Event(),
                    "kind": operation,
                    "snapshot": pending["snapshot"],
                    "source_digest": pending["source_digest"],
                }
                foundation.write_state(
                    foundation.STORAGE / "current.json", {"run_id": pending["run_id"]}
                )
                self.active = job
                threading.Thread(target=self.execute_probe, args=(job,), daemon=True).start()
                return {"run_id": pending["run_id"], "state": "accepted"}
            identity = value["run_id"]
            if self.active is not None and identity == self.active["run_id"]:
                if operation in {"cancel", "cleanup"}:
                    self.active["cancel"].set()
                return {"run_id": identity, "state": "running"}
            if self.recent is not None and identity == self.recent["run_id"]:
                return self.recent
            return {"error": "unknown_run"}

    def execute_probe(self, job: dict[str, object]) -> None:
        identity = str(job["run_id"])
        group = self.cgroup / ("run-" + identity)
        snapshot = job["snapshot"]
        assert isinstance(snapshot, Path)
        process = None
        helper = None
        namespace_fd = -1
        namespace_channel = None
        stdout = bytearray()
        stderr = bytearray()
        stdout_truncated = False
        stderr_truncated = False
        failure_code = None
        termination = "failed"
        result: dict[str, object] = {
            "run_id": identity,
            "state": "failed",
            "source_digest": job["source_digest"],
            "population_empty": False,
            "scratch_destroyed": False,
            "snapshot_destroyed": False,
            "output_truncated": False,
            "stderr_truncated": False,
        }
        try:
            group.mkdir()
            for name, value in foundation.LIMITS.items():
                (group / name).write_text(value)
                if (group / name).read_text().strip() != value:
                    raise foundation.WorkerFailure("resource_limit_mismatch")
            result["limits"] = foundation.LIMITS
            namespace_fd, namespace_channel, helper = foundation.prepare_userns(group)
            root = RELEASE / "rootfs"
            process = subprocess.Popen(
                [
                    str(root / "lib64/ld-linux-x86-64.so.2"),
                    "--library-path",
                    str(root / "usr/lib/x86_64-linux-gnu"),
                    str(root / "runtime/bin/python3.13"),
                    "-I",
                    "-S",
                    "-B",
                    str(RELEASE / "worker/i044a_launch.py"),
                    str(group),
                    str(namespace_fd),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={},
                cwd="/",
                close_fds=True,
                pass_fds=(namespace_fd,),
                start_new_session=True,
            )
            os.close(namespace_fd)
            namespace_fd = -1
            namespace_channel.close()
            namespace_channel = None
            total = 0
            deadline = time.monotonic() + foundation.TIMEOUT
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, True)
                selector.register(process.stderr, selectors.EVENT_READ, False)
                while True:
                    if job["cancel"].is_set():
                        termination = "cancelled"
                        break
                    if time.monotonic() >= deadline:
                        termination = "timeout"
                        break
                    if process.poll() is not None and not selector.get_map():
                        termination = "exited" if process.returncode == 0 else "failed"
                        break
                    for key, _ in selector.select(0.05):
                        chunk = os.read(key.fd, 4096)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(chunk)
                        capture = stdout if key.data else stderr
                        available = max(0, 4096 - len(capture))
                        capture.extend(chunk[:available])
                        if key.data:
                            stdout_truncated |= len(chunk) > available
                        else:
                            stderr_truncated |= len(chunk) > available
                    if total > 16384:
                        termination = "output_limit"
                        failure_code = "output_limit"
                        break
            try:
                checks = json.loads(bytes(stdout).splitlines()[0])
                if set(checks) == CHECKS and all(
                    type(value) is bool for value in checks.values()
                ):
                    result["checks"] = checks
            except (IndexError, TypeError, ValueError):
                pass
            if "checks" not in result and termination != "cancelled":
                failure_code = failure_code or "probe_invalid"
        except foundation.WorkerFailure as error:
            failure_code = error.code
        except Exception:  # noqa: BLE001 - collapse untrusted runtime failures
            failure_code = "internal_failed"
        finally:
            if namespace_fd >= 0:
                os.close(namespace_fd)
            if namespace_channel is not None:
                namespace_channel.close()
            empty = False
            try:
                empty = foundation.kill_population(group)
            except Exception:  # noqa: BLE001 - cleanup must continue after any cgroup error
                failure_code = failure_code or "cleanup_failed"
            try:
                foundation.stop_process(process)
                foundation.stop_process(helper)
                if process is not None:
                    process.stdout.close()
                    process.stderr.close()
                if helper is not None and helper.stderr is not None:
                    captured = helper.stderr.read(4097)
                    available = max(0, 4096 - len(stderr))
                    stderr.extend(captured[:available])
                    stderr_truncated |= len(captured) > available
                    helper.stderr.close()
            except Exception:  # noqa: BLE001 - cleanup must continue after any reap error
                failure_code = failure_code or "cleanup_failed"
            snapshot_destroyed = destroy_snapshot(snapshot) if empty else False
            result["population_empty"] = empty
            result["scratch_destroyed"] = empty
            result["snapshot_destroyed"] = snapshot_destroyed
            result["termination"] = termination
            result["output_truncated"] = stdout_truncated or stderr_truncated
            result["stderr_truncated"] = stderr_truncated
            checks = result.get("checks")
            passed = (
                isinstance(checks, dict)
                and all(checks.values())
                and empty
                and snapshot_destroyed
                and termination in {"exited", "timeout"}
            )
            result["state"] = "passed" if passed else termination
            if not passed and termination != "cancelled":
                result["failure_code"] = failure_code or "probe_failed"
            with self.lock:
                self.blocked = not empty or not snapshot_destroyed
                try:
                    foundation.write_state(foundation.STORAGE / "recent.json", result)
                    if not self.blocked:
                        (foundation.STORAGE / "current.json").unlink(missing_ok=True)
                except Exception:  # noqa: BLE001 - fail closed if durable state cannot be written
                    self.blocked = True
                self.recent = result
                self.active = None


def serve(worker: Worker, client_uid: int) -> None:
    foundation.ENDPOINT.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(foundation.ENDPOINT))
        os.chmod(foundation.ENDPOINT, 0o660)
        os.chown(
            foundation.ENDPOINT,
            -1,
            json.loads(foundation.POLICY.read_bytes())["client_gid"],
        )
        server.listen(8)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(1)
                descriptors: list[int] = []
                try:
                    pid, uid, _ = struct.unpack(
                        "3i",
                        connection.getsockopt(
                            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
                        ),
                    )
                    if uid != client_uid:
                        connection.sendall(foundation.encode({"error": "unauthorized"}))
                        continue
                    data = bytearray()
                    flags = 0
                    while len(data) <= 1024 and not data.endswith(b"\n"):
                        message, ancillary, current_flags, _ = connection.recvmsg(
                            1025 - len(data),
                            socket.CMSG_SPACE(array.array("i").itemsize * 2),
                            socket.MSG_CMSG_CLOEXEC,
                        )
                        flags |= current_flags
                        if not message:
                            break
                        data.extend(message)
                        for level, kind, control in ancillary:
                            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                                values = array.array("i")
                                values.frombytes(
                                    control[
                                        : len(control) - len(control) % values.itemsize
                                    ]
                                )
                                descriptors.extend(values)
                    if (
                        flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC)
                        or len(data) > 1024
                        or data.count(b"\n") != 1
                        or not data.endswith(b"\n")
                    ):
                        raise ValueError("request_frame")
                    value = decode(bytes(data), len(descriptors))
                    connection.sendall(
                        foundation.encode(worker.request(value, pid))
                    )
                except (ValueError, TypeError, OSError, foundation.WorkerFailure):
                    try:
                        connection.sendall(
                            foundation.encode({"error": "invalid_request"})
                        )
                    except OSError:
                        pass
                finally:
                    for descriptor in descriptors:
                        os.close(descriptor)


def main() -> None:
    if len(sys.argv) != 1 or os.geteuid() == 0:
        raise RuntimeError("dedicated_unprivileged_identity_required")
    os.environ.clear()
    os.umask(0o077)
    digest = foundation.trust_check()
    policy_info = foundation.POLICY.stat()
    if policy_info.st_uid != 0 or policy_info.st_mode & 0o022:
        raise RuntimeError("untrusted_policy")
    policy = json.loads(foundation.POLICY.read_bytes())
    info = foundation.STORAGE.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError("private_storage_required")
    with foundation.acquire_worker_lock():
        serve(Worker(foundation.own_cgroup(), digest), policy["client_uid"])


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - startup intentionally exposes one fixed failure
        print("verification_worker_start_failed", file=sys.stderr)
        raise SystemExit(1)
