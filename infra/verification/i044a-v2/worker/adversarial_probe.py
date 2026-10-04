"""Release-owned containment probe; /source is inspected only as untrusted data."""

import ctypes
import errno
import json
import os
import platform
import resource
import signal
import socket
import sys
import time
from pathlib import Path


def absent(path: str) -> bool:
    try:
        Path(path).read_bytes()
    except OSError:
        return True
    return False


def readonly(path: str) -> bool:
    try:
        Path(path).write_text("sandbox-mutation")
    except OSError as error:
        return error.errno in {errno.EROFS, errno.EACCES, errno.ENOENT}
    return False


def network_denied() -> bool:
    try:
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return True
    try:
        connection.settimeout(0.1)
        return connection.connect_ex(("127.0.0.1", 5432)) != 0
    finally:
        connection.close()


def clone_errno(flag: int = 0) -> int:
    if platform.machine() != "x86_64":
        return errno.ENOSYS
    libc = ctypes.CDLL(None, use_errno=True)
    ctypes.set_errno(0)
    result = libc.syscall(56, flag | signal.SIGCHLD, 0, 0, 0, 0)
    if result == 0:
        os._exit(97)
    if result > 0:
        os.waitpid(result, 0)
        return 0
    return ctypes.get_errno()


class CloneArgs(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "flags", "pidfd", "child_tid", "parent_tid", "exit_signal", "stack",
        "stack_size", "tls", "set_tid", "set_tid_size", "cgroup",
    )]


def clone3_errno(flag: int = 0) -> int:
    if platform.machine() != "x86_64":
        return errno.ENOSYS
    libc = ctypes.CDLL(None, use_errno=True)
    arguments = CloneArgs(flags=flag, exit_signal=signal.SIGCHLD)
    ctypes.set_errno(0)
    result = libc.syscall(435, ctypes.byref(arguments), ctypes.sizeof(arguments))
    if result == 0:
        os._exit(98)
    if result > 0:
        os.waitpid(result, 0)
        return 0
    return ctypes.get_errno()


status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
if Path("/proc/self/attr/current").read_text().strip() != "novalton-i044a-bwrap (enforce)":
    raise SystemExit("apparmor_profile_required")
filesystem = os.statvfs("/scratch")
Path("/scratch/write-probe").write_text("ok")
interfaces = Path("/proc/net/dev").read_text().splitlines()[2:]
uid_map = Path("/proc/self/uid_map").read_text().split()
fd_targets = []
for value in os.listdir("/proc/self/fd"):
    try:
        if int(value) > 2:
            fd_targets.append(os.readlink("/proc/self/fd/" + value))
    except FileNotFoundError:
        pass

checks = {
    "python_313": sys.version_info[:2] == (3, 13),
    "environment_minimal": dict(os.environ) == {"PWD": "/scratch"},
    "home_absent": not Path("/home").exists() and not Path("/root").exists(),
    "outside_fixture_absent": absent("/tmp/novalton-host-secret"),
    "git_absent": not Path("/source/.git").exists(),
    "dotenv_absent": not Path("/source/.env").exists() and not Path("/source/.env.test").exists(),
    "provider_secrets_absent": not any(
        name in os.environ
        for name in (
            "GITHUB_TOKEN", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY",
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        )
    ),
    "fds_clean": fd_targets == [],
    "source_readonly": readonly("/source/sandbox-source-mutation"),
    "scratch_writable": Path("/scratch/write-probe").read_text() == "ok",
    "scratch_bounded": filesystem.f_blocks * filesystem.f_frsize == 268435456,
    "host_filesystem_absent": absent("/etc/passwd")
    and absent("/var/lib/novalton-verification/current.json"),
    "mount_escape_absent": absent("/source/../etc/passwd")
    and absent("/scratch/../etc/passwd"),
    "private_pid": os.getpid() < 10 and not Path("/proc/1/root/etc/passwd").exists(),
    "user_namespace_private": len(uid_map) == 3 and uid_map[2] == "1",
    "network_denied": network_denied(),
    "loopback_only": all(line.split(":")[0].strip() == "lo" for line in interfaces),
    "host_api_denied": network_denied(),
    "postgres_denied": network_denied(),
    "docker_absent": not Path("/run/docker.sock").exists()
    and not Path("/var/run/docker.sock").exists(),
    "ssh_agent_absent": "SSH_AUTH_SOCK" not in os.environ and not Path("/run/user").exists(),
    "no_new_privileges": status["NoNewPrivs"].strip() == "1",
    "seccomp_active": status["Seccomp"].strip() == "2",
    "seccomp_filter_present": int(status.get("Seccomp_filters", "0").strip()) >= 1,
    "clone_ordinary_allowed": clone_errno() == 0,
    "clone_newuser_denied": clone_errno(0x10000000) == errno.EPERM,
    "clone_newns_denied": clone_errno(0x00020000) == errno.EPERM,
    "clone_newnet_denied": clone_errno(0x40000000) == errno.EPERM,
    "clone_namespaces_denied": all(
        clone_errno(flag) == errno.EPERM
        for flag in (0x10000000, 0x00020000, 0x40000000)
    ),
    "clone3_ordinary_seccomp_denied": clone3_errno() == errno.EPERM,
    "clone3_newuser_denied": clone3_errno(0x10000000) == errno.EPERM,
    "clone3_namespaces_denied": all(
        clone3_errno(flag) == errno.EPERM
        for flag in (0x10000000, 0x00020000, 0x40000000)
    ),
    "caps_empty": all(
        int(status[name].strip(), 16) == 0
        for name in ("CapEff", "CapPrm", "CapAmb", "CapBnd")
    ),
    "core_disabled": resource.getrlimit(resource.RLIMIT_CORE) == (0, 0),
    "stdin_closed": os.read(0, 1) == b"",
    "no_pty": not os.isatty(0) and not os.isatty(1) and not os.isatty(2),
}

for _ in range(2):
    child = os.fork()
    if child == 0:
        os.setsid()
        grandchild = os.fork()
        if grandchild == 0:
            time.sleep(60)
            os._exit(0)
        time.sleep(60)
        os._exit(0)

checks["descendants_started"] = True
print(json.dumps(checks, sort_keys=True), flush=True)
if Path("/source/apps/api/tests/sandbox_fixtures/output_flood").exists():
    print("x" * 32_768, flush=True)
time.sleep(60)
