"""Narrow release-owned client for the I-044B foundation health boundary."""

from __future__ import annotations

import json
import socket
import sys

ENDPOINT = "/run/novalton-verification/control.sock"


def main() -> None:
    if len(sys.argv) != 1:
        raise SystemExit("I-044B client accepts no operation arguments")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(ENDPOINT)
        response = connection.recv(1024)
    value = json.loads(response)
    if value != {"error": "i044a_overlay_required"}:
        raise RuntimeError("foundation_ipc_contract")
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    main()
