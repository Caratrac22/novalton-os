"""Closed-world I-044B worker primitives shared by the I-044A overlay."""

from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
import re
import socket
import stat
import struct
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

RELEASE = Path(__file__).resolve().parents[2] / "i044b-v2"
ENDPOINT = Path("/run/novalton-verification/control.sock")
POLICY = RELEASE / "policy.json"
STORAGE = Path("/var/lib/novalton-verification")
RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
LIMITS = {"cpu.max": "200000 100000", "memory.max": "1073741824", "memory.swap.max": "0", "pids.max": "32"}
TIMEOUT = 8.0
CLONE_NEWUSER = 0x10000000
PR_SET_DUMPABLE = 4


class WorkerFailure(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def encode(value: dict[str, object]) -> bytes:
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    if len(data) > 8192:
        return b'{"error":"response_bound"}\n'
    return data


def write_state(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_bytes(encode(value))
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def trust_check() -> dict[str, str]:
    root = RELEASE.lstat()
    if root.st_uid != 0 or root.st_gid != 0 or stat.S_IMODE(root.st_mode) != 0o555 or RELEASE.is_symlink():
        raise WorkerFailure("release_untrusted")
    manifest_path = RELEASE / "installed-manifest.json"
    metadata_path = RELEASE / "foundation-metadata.json"
    for control in (manifest_path, metadata_path):
        control_info = control.lstat()
        if (control.is_symlink() or not stat.S_ISREG(control_info.st_mode)
                or control_info.st_uid != 0 or control_info.st_gid != 0
                or stat.S_IMODE(control_info.st_mode) != 0o444):
            raise WorkerFailure("release_untrusted")
    manifest_data = manifest_path.read_bytes()
    manifest = json.loads(manifest_data)
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema", "members"}
        or manifest.get("schema") != "novalton.i044b.installed-manifest.v1"
        or not isinstance(manifest.get("members"), list)
    ):
        raise WorkerFailure("manifest_shape")
    actual: set[str] = set()
    for path in [RELEASE, *RELEASE.rglob("*")]:
        info = path.lstat()
        if path.is_symlink() or info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
            raise WorkerFailure("release_untrusted")
        if path not in {RELEASE, manifest_path, metadata_path}:
            actual.add(path.relative_to(RELEASE).as_posix())
    listed: set[str] = set()
    for entry in manifest["members"]:
        if not isinstance(entry, dict) or set(entry) not in (
            {"path", "type", "uid", "gid", "mode"},
            {"path", "type", "uid", "gid", "mode", "sha256"},
        ):
            raise WorkerFailure("manifest_shape")
        relative = entry["path"]
        if not isinstance(relative, str) or not relative or relative.startswith("/") or ".." in Path(relative).parts or relative in listed:
            raise WorkerFailure("manifest_shape")
        listed.add(relative)
        path = RELEASE / relative
        info = path.lstat()
        actual_type = "directory" if stat.S_ISDIR(info.st_mode) else "regular" if stat.S_ISREG(info.st_mode) else "other"
        if (entry["type"] != actual_type or entry["uid"] != info.st_uid
                or entry["gid"] != info.st_gid
                or entry["mode"] != f"{stat.S_IMODE(info.st_mode):04o}"):
            raise WorkerFailure("release_untrusted")
        if actual_type == "regular":
            if set(entry) != {"path", "type", "uid", "gid", "mode", "sha256"} or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                raise WorkerFailure("manifest_content")
        elif set(entry) != {"path", "type", "uid", "gid", "mode"}:
            raise WorkerFailure("manifest_shape")
    if actual != listed:
        raise WorkerFailure("manifest_shape")
    metadata = json.loads(metadata_path.read_bytes())
    if (not isinstance(metadata, dict) or set(metadata) != {
        "schema", "foundation_input_sha256", "installed_manifest_sha256", "runtime_version"
    } or metadata.get("schema") != "novalton.i044b.foundation-metadata.v1"
        or not isinstance(metadata.get("foundation_input_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", metadata["foundation_input_sha256"]) is None
        or metadata.get("installed_manifest_sha256") != hashlib.sha256(manifest_data).hexdigest()
        or metadata.get("runtime_version") != "3.13.15"):
        raise WorkerFailure("foundation_metadata_shape")
    return metadata


@contextmanager
def acquire_worker_lock():
    descriptor = os.open(STORAGE / "worker.lock", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WorkerFailure("worker_already_active") from error
        yield
    finally:
        os.close(descriptor)


def own_cgroup() -> Path:
    raw = Path("/proc/self/cgroup").read_text().strip().split("::", 1)[1].lstrip("/")
    current = Path("/sys/fs/cgroup") / raw
    if current.name != "supervisor" or current.parent == current:
        raise WorkerFailure("delegated_cgroup_required")
    for controller in ("cpu", "memory", "pids"):
        try:
            with (current.parent / "cgroup.subtree_control").open("a") as stream:
                stream.write("+" + controller)
        except OSError as error:
            raise WorkerFailure("cgroup_controller_required") from error
    return current.parent


def kill_population(group: Path) -> bool:
    try:
        (group / "cgroup.kill").write_text("1")
    except FileNotFoundError:
        return True
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            if not (group / "cgroup.procs").read_text().split():
                group.rmdir()
                return True
        except FileNotFoundError:
            return True
        time.sleep(0.02)
    return False


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.kill()
    process.wait(timeout=3)


def _write_map(name: str, uid: int) -> None:
    if name == "gid_map":
        try:
            Path("/proc/self/setgroups").write_text("deny")
        except FileNotFoundError:
            pass
    Path("/proc/self/" + name).write_text(f"0 {uid} 1\n")


def _userns_helper(channel: socket.socket) -> None:
    parent_uid = os.getuid()
    parent_gid = os.getgid()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.unshare(CLONE_NEWUSER) != 0:
        raise OSError(ctypes.get_errno(), "unshare_user")
    _write_map("uid_map", parent_uid)
    _write_map("gid_map", parent_gid)
    libc.prctl(PR_SET_DUMPABLE, 1, 0, 0, 0)
    Path("/proc/sys/user/max_user_namespaces").write_text("1\n")
    descriptor = os.open("/proc/self/ns/user", os.O_RDONLY | os.O_CLOEXEC)
    try:
        channel.sendmsg([b"R"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, descriptor.to_bytes(4, "little", signed=True))])
    finally:
        os.close(descriptor)
    channel.recv(1)


def prepare_userns(group: Path) -> tuple[int, socket.socket, subprocess.Popen[bytes]]:
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    helper_source = str(RELEASE / "worker/worker.py")
    helper_code = (
        "import importlib.util,socket;"
        f"s=importlib.util.spec_from_file_location('i044b_helper',{helper_source!r});"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "m._userns_helper(socket.socket(fileno=3))"
    )
    process = subprocess.Popen(
        [str(RELEASE / "runtime/bin/python3.13"), "-I", "-S", "-B", "-c", helper_code],
        pass_fds=(child.fileno(),), close_fds=True, env={}, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True,
    )
    child.close()
    try:
        message, ancillary, flags, _ = parent.recvmsg(1, socket.CMSG_SPACE(4))
        if message != b"R" or flags or len(ancillary) != 1:
            raise WorkerFailure("userns_protocol")
        control = ancillary[0]
        if control[:2] != (socket.SOL_SOCKET, socket.SCM_RIGHTS):
            raise WorkerFailure("userns_protocol")
        descriptor = int.from_bytes(control[2][:4], "little", signed=True)
        if not os.readlink(f"/proc/self/fd/{descriptor}").startswith("user:["):
            os.close(descriptor)
            raise WorkerFailure("userns_protocol")
        return descriptor, parent, process
    except Exception:
        parent.close()
        stop_process(process)
        raise


class Worker:
    def __init__(self, cgroup: Path, digest: str):
        self.cgroup = cgroup
        self.digest = digest
        self.lock = threading.RLock()
        self.active: dict[str, object] | None = None
        self.blocked = False
        self.reconciled = False
        self.recent: dict[str, object] | None = None
        current = STORAGE / "current.json"
        if current.exists():
            value = json.loads(current.read_bytes())
            if isinstance(value, dict) and isinstance(value.get("run_id"), str):
                self.recent = {"run_id": value["run_id"], "state": "reconciled", "population_empty": True, "scratch_destroyed": True}
                write_state(STORAGE / "recent.json", self.recent)
                current.unlink(missing_ok=True)
                self.reconciled = True
        elif (STORAGE / "recent.json").exists():
            value = json.loads((STORAGE / "recent.json").read_bytes())
            if isinstance(value, dict):
                self.recent = value


def main() -> None:
    if os.geteuid() == 0 or len(os.sys.argv) != 1:
        raise WorkerFailure("dedicated_unprivileged_identity_required")
    os.environ.clear()
    os.umask(0o077)
    trust_check()
    policy = json.loads(POLICY.read_bytes())
    if (
        set(policy) != {"client_gid", "client_uid"}
        or not isinstance(policy["client_gid"], int)
        or not isinstance(policy["client_uid"], int)
    ):
        raise WorkerFailure("policy_shape")
    if STORAGE.stat().st_uid != os.getuid() or stat.S_IMODE(STORAGE.stat().st_mode) != 0o700:
        raise WorkerFailure("private_storage_required")
    # I-044A replaces this worker with its release-owned protocol implementation.
    # This foundation intentionally exposes no generic execution path by itself.
    with acquire_worker_lock():
        ENDPOINT.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(ENDPOINT))
            os.chmod(ENDPOINT, 0o660)
            os.chown(ENDPOINT, -1, policy["client_gid"])
            server.listen(4)
            while True:
                connection, _ = server.accept()
                with connection:
                    credentials = connection.getsockopt(
                        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
                    )
                    _, uid, _ = struct.unpack("3i", credentials)
                    if uid != policy["client_uid"]:
                        connection.sendall(encode({"error": "unauthorized"}))
                    else:
                        connection.sendall(encode({"error": "i044a_overlay_required"}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("verification_worker_start_failed", file=os.sys.stderr)
        raise SystemExit(1)
