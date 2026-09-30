"""Test-only I-044B interface shim; it does not implement sandbox authority."""

import json
import re
from pathlib import Path

RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
ENDPOINT = Path("/unused/novalton-verification.sock")
POLICY = Path("/unused/novalton-verification-policy.json")
STORAGE = Path("/unused/novalton-verification-storage")
LIMITS: dict[str, str] = {}
TIMEOUT = 0.01


class WorkerFailure(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class Worker:
    """Shape-only base class for I-044A contract unit tests."""


def encode(value: dict[str, object]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode() + b"\n"


def write_state(path: Path, value: dict[str, object]) -> None:
    raise RuntimeError("contract_shim_must_not_persist_state")
