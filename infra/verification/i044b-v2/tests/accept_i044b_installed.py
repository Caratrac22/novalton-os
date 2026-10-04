"""Installed I-044B v2 acceptance from the immutable release itself."""

from __future__ import annotations

import grp
import hashlib
import importlib.util
import json
import os
import socket
import stat
import struct
import subprocess
from pathlib import Path

RELEASE = Path("/opt/novalton-verification/i044b-v2")
UNIT = Path("/etc/systemd/system/novalton-verification.service")
MOUNT_UNIT = Path("/etc/systemd/system/var-lib-novalton\\x2dverification.mount")
SOCKET = Path("/run/novalton-verification/control.sock")


def checked(command: list[str]) -> str:
    return subprocess.check_output(
        command, text=True, env={"PATH": "/usr/bin:/bin"}, stdin=subprocess.DEVNULL
    ).strip()


def main() -> None:
    if os.geteuid() != 0 or Path(__file__).resolve() != RELEASE / "tests/accept_i044b_installed.py":
        raise RuntimeError("installed_root_acceptance_required")
    spec = importlib.util.spec_from_file_location("i044b_provision", RELEASE / "provision.py")
    provision = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(provision)
    foundation_input_sha256 = hashlib.sha256((RELEASE / "foundation-input.json").read_bytes()).hexdigest()
    evidence = provision.verify_release(RELEASE, foundation_input_sha256)
    provision.verify_apparmor(RELEASE)
    anchor = Path("/run/novalton-verification-proc").lstat()
    assert stat.S_ISDIR(anchor.st_mode)
    assert (anchor.st_uid, anchor.st_gid, stat.S_IMODE(anchor.st_mode)) == (0, 0, 0o700)
    # No loader-cache or host-library fallback in the actual bwrap trust chain.
    dependencies = checked([
        str(RELEASE / "bwrap-loader"), "--inhibit-cache", "--library-path",
        str(RELEASE / "rootfs/usr/lib/x86_64-linux-gnu"), "--list", str(RELEASE / "bwrap"),
    ])
    for line in dependencies.splitlines():
        if "=>" in line:
            target = Path(line.split("=>", 1)[1].strip().split()[0])
            if line.split("=>", 1)[0].strip() == "/lib64/ld-linux-x86-64.so.2":
                assert target == RELEASE / "bwrap-loader"
                assert target.read_bytes() == (RELEASE / "rootfs/lib64/ld-linux-x86-64.so.2").read_bytes()
            else:
                assert target.is_relative_to(RELEASE / "rootfs"), str(target)
            assert target.is_file()
    assert evidence["foundation_input_sha256"] == foundation_input_sha256
    assert UNIT.read_bytes() == (RELEASE / "novalton-verification.service").read_bytes()
    unit_info = UNIT.lstat()
    assert stat.S_ISREG(unit_info.st_mode) and not UNIT.is_symlink()
    assert (unit_info.st_uid, unit_info.st_gid, stat.S_IMODE(unit_info.st_mode)) == (0, 0, 0o644)
    assert MOUNT_UNIT.read_bytes() == (RELEASE / "var-lib-novalton\\x2dverification.mount").read_bytes()
    mount_info = MOUNT_UNIT.lstat()
    assert stat.S_ISREG(mount_info.st_mode) and not MOUNT_UNIT.is_symlink()
    assert (mount_info.st_uid, mount_info.st_gid, stat.S_IMODE(mount_info.st_mode)) == (0, 0, 0o644)
    assert checked(["/usr/bin/systemctl", "is-active", "novalton-verification.service"]) == "active"
    assert checked(["/usr/bin/systemctl", "is-active", "var-lib-novalton\\x2dverification.mount"]) == "active"
    assert checked(["/usr/bin/findmnt", "--noheadings", "--output", "FSTYPE", "/var/lib/novalton-verification"]) == "tmpfs"
    assert int(checked(["/usr/bin/findmnt", "--bytes", "--noheadings", "--output", "SIZE", "/var/lib/novalton-verification"])) <= 64 * 1024 * 1024
    properties = checked([
        "/usr/bin/systemctl", "show", "novalton-verification.service",
        "--property=User,Group,NoNewPrivileges,PrivateNetwork,ProtectKernelTunables,CapabilityBoundingSet,AmbientCapabilities,RestrictAddressFamilies,ControlGroup",
    ])
    required = {
        "User=novalton-verify", "Group=novalton-verify", "NoNewPrivileges=yes",
        "PrivateNetwork=yes", "ProtectKernelTunables=yes", "CapabilityBoundingSet=",
        "AmbientCapabilities=",
    }
    assert required <= set(properties.splitlines())
    assert "AF_INET" not in properties and "AF_INET6" not in properties
    assert "AF_UNIX" in properties and "AF_NETLINK" in properties
    socket_info = SOCKET.lstat()
    assert stat.S_ISSOCK(socket_info.st_mode) and not SOCKET.is_symlink()
    assert socket_info.st_gid == grp.getgrnam("novalton-verify-ipc").gr_gid
    assert stat.S_IMODE(socket_info.st_mode) == 0o660
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(str(SOCKET))
        credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, peer_uid, _ = struct.unpack("3i", credentials)
        assert peer_uid != 0
        assert json.loads(connection.recv(1024)) == {"error": "unauthorized"}
    checked([
        "/usr/sbin/runuser", "-u", "novalton-verify-client", "--",
        str(RELEASE / "runtime/bin/python3.13"), "-I", "-S", "-B",
        str(RELEASE / "client/i044b_client.py"),
    ])
    print(json.dumps({"i044b_installed_acceptance": "PASS", **evidence}, sort_keys=True))


if __name__ == "__main__":
    main()
