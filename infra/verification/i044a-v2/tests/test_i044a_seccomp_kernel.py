"""Installed kernel acceptance for the exact installed I-044A seccomp program."""

import ctypes
import errno
import hashlib
import json
import os
import platform
import signal
import stat
import unittest
from pathlib import Path

RELEASE = Path("/opt/novalton-verification/i044a-v2")
SYS_CLONE = 56
SYS_SETNS = 308
SYS_SECCOMP = 317
SYS_CLONE3 = 435
PR_SET_NO_NEW_PRIVS = 38
SECCOMP_SET_MODE_FILTER = 1
CLONE_NEWNS = 0x00020000
CLONE_NEWUSER = 0x10000000
CLONE_NEWNET = 0x40000000


class CloneArgs(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "flags",
            "pidfd",
            "child_tid",
            "parent_tid",
            "exit_signal",
            "stack",
            "stack_size",
            "tls",
            "set_tid",
            "set_tid_size",
            "cgroup",
        )
    ]


class SockFilter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("value", ctypes.c_uint32),
    ]


class SockFprog(ctypes.Structure):
    _fields_ = [("length", ctypes.c_ushort), ("filter", ctypes.POINTER(SockFilter))]


def proc_status() -> tuple[int, int]:
    fields = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
    )
    return int(fields["Seccomp"].strip()), int(fields["Seccomp_filters"].strip())


def stable_process_state() -> dict[str, object]:
    namespace_directory = Path("/proc/self/ns")
    return {
        "cwd": os.getcwd(),
        "egid": os.getegid(),
        "euid": os.geteuid(),
        "gid": os.getgid(),
        "groups": os.getgroups(),
        "limits": Path("/proc/self/limits").read_text(),
        "namespaces": {
            path.name: os.readlink(path)
            for path in sorted(
                namespace_directory.iterdir(), key=lambda item: item.name
            )
        },
        "pid": os.getpid(),
        "uid": os.getuid(),
    }


def verify_regular_root_file(path: Path, mode: int) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise AssertionError(f"installed artifact is not a regular file: {path}")
    if info.st_uid != 0 or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != mode:
        raise AssertionError(f"installed artifact metadata mismatch: {path}")
    return info


def installed_policy() -> tuple[bytes, str, str]:
    release_info = RELEASE.lstat()
    if (
        not stat.S_ISDIR(release_info.st_mode)
        or release_info.st_uid != 0
        or release_info.st_gid != 0
        or stat.S_IMODE(release_info.st_mode) != 0o555
    ):
        raise AssertionError("installed release root metadata mismatch")

    manifest_path = RELEASE / "manifest.json"
    policy_path = RELEASE / "seccomp.bpf"
    verify_regular_root_file(manifest_path, 0o444)
    verify_regular_root_file(policy_path, 0o444)
    if manifest_path.parent.resolve(strict=True) != RELEASE.resolve(strict=True):
        raise AssertionError("installed manifest is outside the installed release")
    if policy_path.parent.resolve(strict=True) != RELEASE.resolve(strict=True):
        raise AssertionError("installed policy is outside the installed release")

    manifest_data = manifest_path.read_bytes()
    manifest_digest = hashlib.sha256(manifest_data).hexdigest()
    metadata = json.loads((RELEASE / "release-metadata.json").read_bytes())
    if (not isinstance(metadata, dict)
            or metadata.get("schema") != "novalton.i044a.release-metadata.v1"
            or metadata.get("installed_manifest_sha256") != manifest_digest):
        raise AssertionError("installed release manifest identity mismatch")
    manifest = json.loads(manifest_data)
    if not isinstance(manifest, dict) or not isinstance(
        manifest.get("seccomp.bpf"), str
    ):
        raise TypeError("installed release manifest has no seccomp.bpf identity")

    policy = policy_path.read_bytes()
    policy_digest = hashlib.sha256(policy).hexdigest()
    if policy_digest != manifest["seccomp.bpf"]:
        raise AssertionError(
            "installed seccomp.bpf digest does not match installed manifest"
        )
    return policy, policy_digest, manifest_digest


def reap_exact_child(pid: int) -> None:
    while True:
        try:
            waited, status = os.waitpid(pid, 0)
            break
        except InterruptedError:
            continue
    if waited != pid or not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        raise AssertionError(f"child {pid} did not exit cleanly: {status}")
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return
    raise AssertionError(f"child {pid} was not completely reaped")


def setns_invalid_fd_errno() -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    ctypes.set_errno(0)
    result = libc.syscall(SYS_SETNS, ctypes.c_int(-1), ctypes.c_int(0))
    if result != -1:
        raise AssertionError("invalid namespace FD unexpectedly accepted")
    return ctypes.get_errno()


def clone3_once(arguments: CloneArgs) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    ctypes.set_errno(0)
    result = libc.syscall(SYS_CLONE3, ctypes.byref(arguments), ctypes.sizeof(arguments))
    if result == 0:
        os._exit(0)
    if result > 0:
        reap_exact_child(result)
        return 0
    if result == -1:
        return ctypes.get_errno()
    raise AssertionError(f"unexpected clone3 return value: {result}")


def clone_once(flags: int) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    ctypes.set_errno(0)
    result = libc.syscall(SYS_CLONE, flags | signal.SIGCHLD, 0, 0, 0, 0)
    if result == 0:
        os._exit(0)
    if result > 0:
        reap_exact_child(result)
        return 0
    if result == -1:
        return ctypes.get_errno()
    raise AssertionError(f"unexpected clone return value: {result}")


def fork_once() -> int:
    try:
        pid = os.fork()
    except OSError as error:
        return error.errno
    if pid == 0:
        os._exit(0)
    reap_exact_child(pid)
    return 0


def load_exact_policy(policy: bytes) -> None:
    if not policy or len(policy) % ctypes.sizeof(SockFilter):
        raise AssertionError("invalid installed policy size")
    count = len(policy) // ctypes.sizeof(SockFilter)
    instructions = (SockFilter * count).from_buffer_copy(policy)
    program = SockFprog(count, instructions)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS")
    if (
        libc.syscall(SYS_SECCOMP, SECCOMP_SET_MODE_FILTER, 0, ctypes.byref(program))
        != 0
    ):
        raise OSError(ctypes.get_errno(), "SECCOMP_SET_MODE_FILTER")


class I044AInstalledSeccompKernelTests(unittest.TestCase):
    def test_installed_policy_same_process_clone3_attribution(self):
        self.assertEqual(platform.machine(), "x86_64", "I-044A policy requires x86_64")
        policy, policy_digest, manifest_digest = installed_policy()
        mode_before, filters_before = proc_status()
        state_before = stable_process_state()

        ordinary_arguments = CloneArgs(flags=0, exit_signal=signal.SIGCHLD)
        argument_identity = bytes(ordinary_arguments)
        pre_filter_errno = clone3_once(ordinary_arguments)
        self.assertEqual(
            pre_filter_errno,
            0,
            f"ordinary clone3 must succeed before I-044A installation; errno={pre_filter_errno}",
        )
        self.assertEqual(bytes(ordinary_arguments), argument_identity)

        setns_before = setns_invalid_fd_errno()
        self.assertEqual(setns_before, errno.EBADF)
        load_exact_policy(policy)
        setns_after = setns_invalid_fd_errno()
        self.assertEqual(setns_after, errno.EPERM)
        mode_after, filters_after = proc_status()
        self.assertEqual(mode_after, 2, "seccomp filter mode must be active")
        self.assertEqual(
            filters_after, filters_before + 1, "exactly one I-044A filter must be added"
        )
        self.assertEqual(stable_process_state(), state_before)

        self.assertEqual(bytes(ordinary_arguments), argument_identity)
        post_filter_errno = clone3_once(ordinary_arguments)
        self.assertEqual(post_filter_errno, errno.EPERM)
        self.assertEqual(bytes(ordinary_arguments), argument_identity)

        self.assertEqual(clone_once(0), 0)
        self.assertEqual(fork_once(), 0)
        self.assertEqual(clone_once(CLONE_NEWUSER), errno.EPERM)
        self.assertEqual(clone_once(CLONE_NEWNS), errno.EPERM)
        self.assertEqual(clone_once(CLONE_NEWNET), errno.EPERM)
        self.assertEqual(
            clone3_once(CloneArgs(flags=CLONE_NEWUSER, exit_signal=signal.SIGCHLD)),
            errno.EPERM,
        )
        self.assertEqual(
            clone3_once(CloneArgs(flags=CLONE_NEWNS, exit_signal=signal.SIGCHLD)),
            errno.EPERM,
        )
        self.assertEqual(
            clone3_once(CloneArgs(flags=CLONE_NEWNET, exit_signal=signal.SIGCHLD)),
            errno.EPERM,
        )

        print(
            json.dumps(
                {
                    "argument_bytes_sha256": hashlib.sha256(
                        argument_identity
                    ).hexdigest(),
                    "clone3_post_filter_errno": post_filter_errno,
                    "clone3_pre_filter_errno": pre_filter_errno,
                    "setns_pre_filter_errno": setns_before,
                    "setns_post_filter_errno": setns_after,
                    "filters_after": filters_after,
                    "filters_before": filters_before,
                    "mode_after": mode_after,
                    "mode_before": mode_before,
                    "policy_sha256": policy_digest,
                    "installed_manifest_sha256": manifest_digest,
                    "stable_process_state_sha256": hashlib.sha256(
                        json.dumps(state_before, sort_keys=True).encode()
                    ).hexdigest(),
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
