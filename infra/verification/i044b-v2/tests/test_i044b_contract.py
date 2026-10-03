"""Static closed-world regression checks for source-built I-044B v2."""

import ast
import hashlib
import json
from pathlib import Path

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
for required in (
    "foundation_input_sha256", "installed_manifest_sha256",
    "novalton.i044b.foundation-metadata.v1", "novalton.i044b.installed-manifest.v1",
):
    assert required in provision_source
    assert required in worker_source
print(json.dumps({"foundation_input_sha256": foundation_input_sha256, "i044b_source_contract": "PASS"}, sort_keys=True))
