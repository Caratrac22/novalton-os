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
    }))


if __name__ == "__main__":
    main()
