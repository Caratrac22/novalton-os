"""Static closed-world regression checks for source-built I-044B v2."""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
UNIT = (ROOT / "novalton-verification.service").read_text()
MOUNT_UNIT = (ROOT / "var-lib-novalton\\x2dverification.mount").read_text()
LOCK = json.loads((ROOT / "runtime.lock.json").read_bytes())
FOUNDATION_INPUT_DATA = (ROOT / "foundation-input.json").read_bytes()
FOUNDATION_INPUT = json.loads(FOUNDATION_INPUT_DATA)
TREE = ast.parse((ROOT / "provision.py").read_text())

assert LOCK["format"] == 1
assert LOCK["cpython"]["version"] == "3.13.15"
assert len(LOCK["cpython"]["sha256"]) == 64
assert LOCK["bubblewrap"]["version"] == "0.9.0-1ubuntu0.3"
assert len(LOCK["bubblewrap"]["sha256"]) == 64
assert LOCK["bubblewrap"]["binary_sha256"] == FOUNDATION_INPUT["bubblewrap_sha256"]
for required in (
    "User=novalton-verify",
    "NoNewPrivileges=yes",
    "CapabilityBoundingSet=",
    "AmbientCapabilities=",
    "PrivateNetwork=yes",
    "ProtectKernelTunables=yes",
    "RestrictAddressFamilies=AF_UNIX AF_NETLINK",
    "Delegate=cpu memory pids",
    "KillMode=control-group",
):
    assert required in UNIT
for forbidden in ("AF_INET", "AF_INET6", "EnvironmentFile=", "ReadWritePaths=/home"):
    assert forbidden not in UNIT
for required in ("What=tmpfs", "Where=/var/lib/novalton-verification", "size=64M", "nosuid", "nodev", "noexec"):
    assert required in MOUNT_UNIT
assert all(not isinstance(node, ast.Call) or not (isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}) for node in ast.walk(TREE))
assert set(FOUNDATION_INPUT) == {
    "schema", "runtime_version", "cpython_source_sha256", "bubblewrap_sha256", "source"
}
assert FOUNDATION_INPUT["schema"] == "novalton.i044b.foundation-input.v1"
assert FOUNDATION_INPUT["runtime_version"] == LOCK["cpython"]["version"]
assert FOUNDATION_INPUT["cpython_source_sha256"] == LOCK["cpython"]["sha256"]
for relative, expected in FOUNDATION_INPUT["source"].items():
    assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
foundation_input_sha256 = hashlib.sha256(FOUNDATION_INPUT_DATA).hexdigest()
assert foundation_input_sha256 in (ROOT / "root-handoff.sh").read_text()
provision_source = (ROOT / "provision.py").read_text()
worker_source = (ROOT / "worker/worker.py").read_text()
assert 'os.chown(ENDPOINT, -1, policy["client_gid"])' in worker_source
helper_source = (ROOT / "worker/userns-helper.c").read_text()
assert "-c" not in worker_source
assert helper_source.index("uid_t uid = getuid()") < helper_source.index("unshare(CLONE_NEWUSER)")
assert "PR_GET_NO_NEW_PRIVS" in helper_source and "SYS_capget" in helper_source
assert "peer.pid != getppid()" in helper_source
assert 'write_fixed("/proc/sys/user/max_user_namespaces", "0\\n")' in helper_source
assert '"/run/novalton-verification-proc/full/self/status"' in helper_source
assert "anchor_as_host" in helper_source and "anchor_as_namespace" in helper_source
assert "BindPaths=/proc/1/root/proc:/run/novalton-verification-proc/full" in UNIT
assert "proc_anchor_untrusted" in worker_source
assert "runtime_rootfs(prefix, candidate / \"rootfs\", bubblewrap)" in provision_source
assert '"novalton-i044b-userns (enforce)\\n"' in helper_source
policy = (ROOT / "novalton-userns.apparmor").read_text()
assert "userns create," in policy and "capability sys_admin," in policy
assert "profile novalton-i044b-userns /opt/novalton-verification/i044b-v2/userns-helper" in policy
assert "profile novalton-i044a-bwrap /opt/novalton-verification/i044b-v2/bwrap-loader" in policy
for forbidden in ("flags=(unconfined", "default_allow", "complain", " ux,", "change_profile", "\n  /** rw,", "\n  mount,", "\n  capability,", "\n  network,"):
    assert forbidden not in policy
for required in (
    "foundation_input_sha256", "installed_manifest_sha256",
    "novalton.i044b.foundation-metadata.v1", "novalton.i044b.installed-manifest.v1",
):
    assert required in provision_source
    assert required in worker_source

# pass_fds preserves descriptor numbers; it does not remap the socket to fd 3.
# Exercise the launcher contract without pretending to test kernel isolation.
spec = importlib.util.spec_from_file_location("i044b_contract_worker", ROOT / "worker/worker.py")
assert spec is not None and spec.loader is not None
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
parent, child, process = Mock(), Mock(), Mock()
child.fileno.return_value = 37
parent.recvmsg.return_value = (b"", [], 0, None)
process.poll.return_value = 0
with patch.object(worker.socket, "socketpair", return_value=(parent, child)), patch.object(
    worker.subprocess, "Popen", return_value=process
) as launch:
    try:
        worker.prepare_userns(Path("/unused-contract-cgroup/run-" + "a" * 32))
    except worker.WorkerFailure as error:
        assert error.code == "userns_protocol"
    else:
        raise AssertionError("missing namespace handoff must fail closed")
assert launch.call_args.kwargs["pass_fds"] == (37,)
assert launch.call_args.args[0] == [str(worker.RELEASE / "userns-helper"), "37", "a" * 32]
assert launch.call_args.kwargs["env"] == {}
assert launch.call_args.kwargs["close_fds"] is True
parent.close.assert_called_once()
child.close.assert_called_once()
parent.settimeout.assert_called_once_with(worker.TIMEOUT)
for message, expected in (
    (b"E:unshare:1", "userns_unshare_errno_1"),
    (b"E:namespace_limit:30", "userns_namespace_limit_errno_30"),
    (b"E:attacker_path:1", "userns_protocol"),
):
    parent.recvmsg.return_value = (message, [], 0, None)
    with patch.object(worker.socket, "socketpair", return_value=(parent, child)), patch.object(
        worker.subprocess, "Popen", return_value=process
    ):
        try:
            worker.prepare_userns(Path("/unused-contract-cgroup/run-" + "a" * 32))
        except worker.WorkerFailure as error:
            assert error.code == expected
        else:
            raise AssertionError("helper failure must not authorize execution")
print(json.dumps({"foundation_input_sha256": foundation_input_sha256, "i044b_source_contract": "PASS"}, sort_keys=True))
