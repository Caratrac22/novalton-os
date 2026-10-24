"""AES-256-GCM envelope with immutable owner/scope/provider associated data.

The master keyring is supplied out of band by the host, never by SQL or the browser.
"""

import base64
import binascii
import json
import os
import re
import secrets
from dataclasses import dataclass
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultUnavailable(Exception):
    """Absent, incorrect or damaged key material; never reveal the payload."""


@dataclass(frozen=True)
class Keyring:
    active_id: str
    keys: dict[str, bytes]

    @classmethod
    def from_environment(cls) -> "Keyring":
        encoded = os.environ.get("NOVALTON_BYOK_KEYRING")
        active = os.environ.get("NOVALTON_BYOK_ACTIVE_KEY_ID", "")
        if not encoded or not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", active):
            raise VaultUnavailable("Provider vault is not configured")
        try:
            raw = json.loads(encoded)
            if not isinstance(raw, dict) or not 1 <= len(raw) <= 8:
                raise ValueError
            keys = {}
            for label, value in raw.items():
                if not isinstance(label, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", label):
                    raise ValueError
                if not isinstance(value, str):
                    raise ValueError
                key = base64.b64decode(value, validate=True)
                if len(key) != 32:
                    raise ValueError
                keys[label] = key
            if active not in keys:
                raise ValueError
        except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
            raise VaultUnavailable("Provider vault configuration is invalid") from exc
        return cls(active_id=active, keys=keys)

    @staticmethod
    def associated_data(owner: UUID, tenant: UUID, workspace: UUID, provider: str) -> bytes:
        return f"novalton-byok-v1:{owner}:{tenant}:{workspace}:{provider}".encode("ascii")

    def encrypt(
        self, payload: str, *, owner: UUID, tenant: UUID, workspace: UUID, provider: str
    ) -> tuple[str, bytes, bytes]:
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self.keys[self.active_id]).encrypt(
            nonce, payload.encode("utf-8"), self.associated_data(owner, tenant, workspace, provider)
        )
        return self.active_id, nonce, ciphertext

    def decrypt(
        self,
        key_id: str,
        nonce: bytes,
        ciphertext: bytes,
        *,
        owner: UUID,
        tenant: UUID,
        workspace: UUID,
        provider: str,
    ) -> str:
        key = self.keys.get(key_id)
        if key is None:
            raise VaultUnavailable("Provider vault key unavailable")
        try:
            return (
                AESGCM(key)
                .decrypt(
                    nonce, ciphertext, self.associated_data(owner, tenant, workspace, provider)
                )
                .decode("utf-8")
            )
        except (InvalidTag, ValueError, UnicodeError) as exc:
            raise VaultUnavailable("Provider vault record unavailable") from exc
