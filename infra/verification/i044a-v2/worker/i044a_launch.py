"""Trusted fixed launcher for the I-044A repository containment probe."""

import os
import re
import sys
from pathlib import Path

release = Path(__file__).resolve().parent.parent
current = Path("/sys/fs/cgroup") / Path("/proc/self/cgroup").read_text().strip().split(
    "::", 1
)[1].lstrip("/")
if len(sys.argv) != 3:
    raise SystemExit(2)
group = Path(sys.argv[1])
userns_fd = int(sys.argv[2])
if current.name != "supervisor" or group.parent != current.parent:
    raise SystemExit(2)
if not re.fullmatch(r"run-[0-9a-f]{32}", group.name):
    raise SystemExit(2)
try:
    namespace = os.readlink(f"/proc/self/fd/{userns_fd}")
except OSError:
    raise SystemExit(2)
if not namespace.startswith("user:["):
    raise SystemExit(2)
(group / "cgroup.procs").write_text(str(os.getpid()))
root = release / "rootfs"
snapshot = Path("/var/lib/novalton-verification") / ("snapshot-" + group.name[4:])
if not snapshot.is_dir():
    raise SystemExit(2)
seccomp_fd = os.open(release / "seccomp.bpf", os.O_RDONLY | os.O_CLOEXEC)
os.set_inheritable(seccomp_fd, True)
argv = [
    str(release / "bwrap"),
    "--userns",
    str(userns_fd),
    "--sync-fd",
    str(userns_fd),
    "--assert-userns-disabled",
    "--unshare-ipc",
    "--unshare-pid",
    "--unshare-net",
    "--unshare-uts",
    "--unshare-cgroup-try",
    "--die-with-parent",
    "--new-session",
    "--cap-drop",
    "ALL",
    "--clearenv",
    "--ro-bind",
    str(root),
    "/",
    "--ro-bind",
    str(snapshot),
    "/source",
    "--proc",
    "/proc",
    "--dev",
    "/dev",
    "--size",
    "268435456",
    "--tmpfs",
    "/scratch",
    "--seccomp",
    str(seccomp_fd),
    "--chdir",
    "/scratch",
    "/runtime/bin/python3.13",
    "-I",
    "-S",
    "-B",
    "/runtime/i044a_probe.py",
]
loader = "/opt/novalton-verification/i044b-v2/bwrap-loader"
argv = [loader, "--library-path", str(root / "usr/lib/x86_64-linux-gnu"), *argv]
os.execve(loader, argv, {})
