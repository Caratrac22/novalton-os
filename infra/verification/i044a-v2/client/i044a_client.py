"""Release-owned closed-world IPC client for installed I-044A acceptance."""

from __future__ import annotations

import array
import json
import os
import re
import socket
import sys
import time

ENDPOINT = "/run/novalton-verification/control.sock"
FOUNDATION_INPUT_SHA256 = "aec46813d4f940b49fb30c64d43d738e9eca5c25330db02f06a4c4e75e25d367"
MAX_REQUEST_BYTES = 1024
MAX_RESPONSE_BYTES = 8192
RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
CAPABILITY = re.compile(r"[0-9a-f]{64}\Z")
RELEASE_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
SIMPLE_ACTIONS = frozenset({"health", "security", "start", "verify"})
RUN_ACTIONS = frozenset({"cancel", "cleanup", "result"})


def request(value: dict[str, str], descriptors: tuple[int, ...] = ()) -> dict[str, object]:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    if len(encoded) > MAX_REQUEST_BYTES:
        raise RuntimeError("request_bound")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(ENDPOINT)
        if descriptors:
            connection.sendmsg(
                [encoded],
                [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", descriptors))],
            )
        else:
            connection.sendall(encoded)
        response = bytearray()
        while not response.endswith(b"\n"):
            chunk = connection.recv(MAX_RESPONSE_BYTES + 1 - len(response))
            if not chunk:
                raise RuntimeError("empty_response")
            response.extend(chunk)
            if len(response) > MAX_RESPONSE_BYTES:
                raise RuntimeError("response_bound")
    decoded = json.loads(response)
    if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
        raise RuntimeError("invalid_response")
    return decoded


def health(expected_release: str, expected_i044a_input: str | None = None) -> dict[str, object]:
    value = request({"op": "health"})
    if (
        value.get("state") != "ready"
        or value.get("definition") != "repository-probe-v1"
        or value.get("foundation_input_sha256") != FOUNDATION_INPUT_SHA256
        or value.get("installed_manifest_sha256") != expected_release
        or not isinstance(value.get("foundation_installed_manifest_sha256"), str)
        or RELEASE_DIGEST.fullmatch(value["foundation_installed_manifest_sha256"]) is None
        or not isinstance(value.get("i044a_input_sha256"), str)
        or RELEASE_DIGEST.fullmatch(value["i044a_input_sha256"]) is None
        or (expected_i044a_input is not None and value["i044a_input_sha256"] != expected_i044a_input)
        or value.get("db_mode") is not False
    ):
        raise RuntimeError("sandbox_definition_mismatch")
    return value


def prepare() -> tuple[str, str]:
    prepared = request({"op": "prepare"})
    capability = prepared.get("capability")
    snapshot_digest = prepared.get("source_digest")
    if (
        prepared.get("state") != "prepared"
        or not isinstance(capability, str)
        or CAPABILITY.fullmatch(capability) is None
        or not isinstance(snapshot_digest, str)
        or RELEASE_DIGEST.fullmatch(snapshot_digest) is None
    ):
        raise RuntimeError("invalid_response")
    return capability, snapshot_digest


def verify(expected_release: str) -> dict[str, object]:
    health(expected_release)
    capability, snapshot_digest = prepare()
    accepted = request({"op": "verify", "capability": capability})
    run_id = accepted.get("run_id")
    if (
        accepted.get("state") != "accepted"
        or not isinstance(run_id, str)
        or RUN_ID.fullmatch(run_id) is None
    ):
        raise RuntimeError("invalid_response")
    deadline = time.monotonic() + 15
    while True:
        value = request({"op": "result", "run_id": run_id})
        if value.get("state") != "running":
            break
        if time.monotonic() >= deadline:
            request({"op": "cancel", "run_id": run_id})
            raise RuntimeError("adapter_timeout")
        time.sleep(0.05)
    if value.get("run_id") != run_id or value.get("source_digest") != snapshot_digest:
        raise RuntimeError("snapshot_identity_mismatch")
    return value


def security(expected_release: str) -> dict[str, object]:
    health(expected_release)
    reader, writer = os.pipe()
    try:
        arbitrary = request({"op": "prepare"}, (reader,))
        extra = request({"op": "prepare"}, (reader, writer))
    finally:
        os.close(reader)
        os.close(writer)
    wrong_digest = request({"op": "prepare", "source_digest": "0" * 64})
    capability, _ = prepare()
    wrong = request({"op": "verify", "capability": "0" * 64})
    reader, writer = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(reader)
        os.write(writer, json.dumps(request({"op": "verify", "capability": capability})).encode())
        os._exit(0)
    os.close(writer)
    other_pid = json.loads(os.read(reader, MAX_RESPONSE_BYTES))
    os.close(reader)
    os.waitpid(child, 0)
    accepted = request({"op": "verify", "capability": capability})
    replay = request({"op": "verify", "capability": capability})
    return {
        "accepted": accepted,
        "arbitrary_fd": arbitrary,
        "extra_fd": extra,
        "other_pid": other_pid,
        "replay": replay,
        "wrong_capability": wrong,
        "wrong_digest": wrong_digest,
    }


def start(expected_release: str) -> dict[str, object]:
    health(expected_release)
    prepared = request({"op": "prepare"})
    if "error" in prepared:
        return prepared
    capability = prepared.get("capability")
    snapshot_digest = prepared.get("source_digest")
    if (
        prepared.get("state") != "prepared"
        or not isinstance(capability, str)
        or CAPABILITY.fullmatch(capability) is None
        or not isinstance(snapshot_digest, str)
        or RELEASE_DIGEST.fullmatch(snapshot_digest) is None
    ):
        raise RuntimeError("invalid_response")
    return request({"op": "verify", "capability": capability})


def run_action(expected_release: str, action: str, run_id: str) -> dict[str, object]:
    if RUN_ID.fullmatch(run_id) is None:
        raise RuntimeError("run_identity")
    health(expected_release)
    return request({"op": action, "run_id": run_id})


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "usage: i044a_client.py <release-digest> <health|security|start|verify> "
            "or <release-digest> <cancel|cleanup|result> <run-id>"
        )
    expected_release = sys.argv[1]
    action = sys.argv[2]
    if RELEASE_DIGEST.fullmatch(expected_release) is None:
        raise RuntimeError("release_identity")
    if action in SIMPLE_ACTIONS and len(sys.argv) == 3:
        if action == "health":
            result = health(expected_release)
        elif action == "verify":
            result = verify(expected_release)
        elif action == "security":
            result = security(expected_release)
        else:
            result = start(expected_release)
    elif action in RUN_ACTIONS and len(sys.argv) == 4:
        result = run_action(expected_release, action, sys.argv[3])
    else:
        raise RuntimeError("action_shape")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - acceptance emits bounded diagnostics
        print(json.dumps({"error": str(error)}, sort_keys=True))
