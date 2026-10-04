"""CI root acceptance: unload only our two profiles, prove fail closed, reload.

No checkout writes, host sysctls, broad profiles or arbitrary commands. Profile
reload is unconditional; the next fresh runner also starts from reviewed input.
The ordinary I-044A installed suite then proves the complete positive path.
"""

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

BASE = Path("/opt/novalton-verification/i044b-v2")
A = Path("/opt/novalton-verification/i044a-v2")
POLICY = Path("/etc/apparmor.d/novalton-verification-userns")


def checked(argv: list[str]) -> bytes:
    return subprocess.check_output(argv, env={}, stdin=subprocess.DEVNULL, timeout=30)


def verify() -> dict[str, object]:
    identity = hashlib.sha256((A / "manifest.json").read_bytes()).hexdigest()
    return json.loads(checked([
        "/usr/sbin/runuser", "-u", "novalton-verify-client", "--",
        str(A / "rootfs/runtime/bin/python3.13"), "-I", "-S", "-B",
        str(A / "client/i044a_client.py"), identity, "verify",
    ]))


def main() -> None:
    if os.geteuid() != 0 or Path(__file__).resolve() != BASE / "tests/accept_apparmor_installed.py":
        raise RuntimeError("installed_root_acceptance_required")
    spec = importlib.util.spec_from_file_location("i044b_verifier", BASE / "provision.py")
    assert spec is not None and spec.loader is not None
    provision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provision)
    provision.verify_release(BASE)
    provision.verify_apparmor(BASE)
    main_pid = int(checked([
        "/usr/bin/systemctl", "show", "novalton-verification.service",
        "--property=MainPID", "--value",
    ]))
    assert main_pid > 1
    status = dict(line.split(":", 1) for line in Path(f"/proc/{main_pid}/status").read_text().splitlines())
    assert status["NoNewPrivs"].strip() == "1"
    for name in ("CapEff", "CapPrm", "CapInh", "CapAmb", "CapBnd"):
        assert int(status[name].strip(), 16) == 0
    host_policy = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns").read_bytes()
    assert host_policy.strip() == b"1"
    host_mount = Path("/proc/1/ns/mnt").readlink()
    host_limit = Path("/proc/sys/user/max_user_namespaces").read_bytes()
    # An ELF loader can start Python with arbitrary arguments. It must never
    # be an AppArmor attachment granting generic namespace construction.
    loader_negative = checked([
        "/usr/sbin/runuser", "-u", "novalton-verify-client", "--",
        "/usr/bin/env", "-i", "PYTHONHOME=" + str(BASE / "runtime"),
        str(BASE / "bwrap-loader"), "--inhibit-cache", "--library-path",
        str(A / "rootfs/usr/lib/x86_64-linux-gnu"),
        str(BASE / "runtime/bin/python3.13"), "-S", "-B", "-c",
        """import ctypes,errno,os
c=ctypes.CDLL(None,use_errno=True)
uid=os.getuid()
assert c.prctl(38,1,0,0,0)==0
assert 'novalton-i044' not in open('/proc/self/attr/current').read()
if c.unshare(0x10000000)==-1:
    assert ctypes.get_errno()==errno.EPERM
else:
    fd=-1
    try:
        fd=os.open('/proc/self/uid_map',os.O_WRONLY)
        os.write(fd,f'0 {uid} 1\\n'.encode())
    except OSError as error:
        assert error.errno==errno.EPERM
    else:
        raise AssertionError('generic loader acquired namespace authority')
    finally:
        if fd>=0:
            os.close(fd)
print('generic_loader_namespace_denied')
""",
    ])
    assert loader_negative.strip() == b"generic_loader_namespace_denied"
    entry_negative = checked([
        "/usr/sbin/runuser", "-u", "novalton-verify", "--",
        str(BASE / "runtime/bin/python3.13"), "-I", "-S", "-B", "-c",
        ("import ctypes,os,subprocess;assert ctypes.CDLL(None).prctl(38,1,0,0,0)==0;"
        "fd=os.open('/proc/self/ns/user',os.O_RDONLY);"
        "r=subprocess.run(['/opt/novalton-verification/i044b-v2/bwrap-entry',"
        "str(fd),'a'*32],env={},pass_fds=(fd,));"
        "os.close(fd);assert r.returncode==2;print('outside_service_entry_rejected')"),
    ])
    assert entry_negative.strip() == b"outside_service_entry_rejected"
    try:
        checked(["/usr/sbin/apparmor_parser", "--remove", str(POLICY)])
        try:
            provision.verify_apparmor(BASE)
        except RuntimeError as error:
            assert str(error) == "apparmor_profile_not_enforced"
        else:
            raise AssertionError("missing enforced policy accepted")
        result = verify()
        assert result["state"] == "failed", result.get("failure_code")
        assert result["failure_code"] == "userns_precondition_errno_1"
        for name in ("population_empty", "scratch_destroyed", "snapshot_destroyed"):
            assert result[name] is True
    finally:
        checked(["/usr/sbin/apparmor_parser", "--replace", "--skip-cache", str(POLICY)])
    provision.verify_apparmor(BASE)
    result = verify()
    assert result["state"] == "passed", result.get("failure_code")
    assert all(result["checks"].values())
    for name in (
        "clone_namespaces_denied", "clone3_namespaces_denied", "mount_escape_absent",
        "user_namespace_private", "fds_clean", "seccomp_active", "caps_empty",
    ):
        assert result["checks"][name] is True
    for name in ("population_empty", "scratch_destroyed", "snapshot_destroyed"):
        assert result[name] is True
    assert Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns").read_bytes() == host_policy
    assert Path("/proc/1/ns/mnt").readlink() == host_mount
    assert Path("/proc/sys/user/max_user_namespaces").read_bytes() == host_limit
    print(json.dumps({
        "apparmor_negative": "PASS", "apparmor_positive": "PASS", "cleanup": "PASS",
        "worker_host_caps_empty": "PASS", "namespace_escape_denied": "PASS",
        "host_sysctl_unchanged": "PASS", "host_mount_namespace_unchanged": "PASS",
        "generic_loader_authority_denied": "PASS", "outside_service_entry_rejected": "PASS",
    }))


if __name__ == "__main__":
    main()
