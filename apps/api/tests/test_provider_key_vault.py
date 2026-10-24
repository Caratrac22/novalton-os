"""Deterministic AEAD security contract without real provider credentials."""

import base64
import json
from uuid import uuid4

import pytest

from novalton_api.modules.provider_keys.vault import Keyring, VaultUnavailable


def test_vault_binding_rotation_and_missing_keys(monkeypatch):
    first, second = b"a" * 32, b"b" * 32
    monkeypatch.setenv(
        "NOVALTON_BYOK_KEYRING",
        json.dumps(
            {
                "v1": base64.b64encode(first).decode(),
                "v2": base64.b64encode(second).decode(),
            }
        ),
    )
    monkeypatch.setenv("NOVALTON_BYOK_ACTIVE_KEY_ID", "v1")
    ring = Keyring.from_environment()
    owner, tenant, workspace = uuid4(), uuid4(), uuid4()
    key_id, nonce, ciphertext = ring.encrypt(
        "fake-test-credential",
        owner=owner,
        tenant=tenant,
        workspace=workspace,
        provider="openrouter",
    )
    assert b"fake-test-credential" not in ciphertext
    assert (
        ring.decrypt(
            key_id,
            nonce,
            ciphertext,
            owner=owner,
            tenant=tenant,
            workspace=workspace,
            provider="openrouter",
        )
        == "fake-test-credential"
    )
    for wrong in ({"owner": uuid4()}, {"workspace": uuid4()}, {"provider": "openai_compatible"}):
        scope = {
            "owner": owner,
            "tenant": tenant,
            "workspace": workspace,
            "provider": "openrouter",
        } | wrong
        with pytest.raises(VaultUnavailable):
            ring.decrypt(key_id, nonce, ciphertext, **scope)
    with pytest.raises(VaultUnavailable):
        ring.decrypt(
            key_id,
            nonce,
            ciphertext[:-1] + b"x",
            owner=owner,
            tenant=tenant,
            workspace=workspace,
            provider="openrouter",
        )
    monkeypatch.setenv("NOVALTON_BYOK_ACTIVE_KEY_ID", "v2")
    rotated = Keyring.from_environment()
    assert (
        rotated.decrypt(
            key_id,
            nonce,
            ciphertext,
            owner=owner,
            tenant=tenant,
            workspace=workspace,
            provider="openrouter",
        )
        == "fake-test-credential"
    )
    new_id, _, _ = rotated.encrypt(
        "another-fake", owner=owner, tenant=tenant, workspace=workspace, provider="openrouter"
    )
    assert new_id == "v2"
    monkeypatch.setenv(
        "NOVALTON_BYOK_KEYRING", json.dumps({"v2": base64.b64encode(second).decode()})
    )
    with pytest.raises(VaultUnavailable):
        Keyring.from_environment().decrypt(
            key_id,
            nonce,
            ciphertext,
            owner=owner,
            tenant=tenant,
            workspace=workspace,
            provider="openrouter",
        )


def test_vault_fails_closed_without_master_key(monkeypatch):
    monkeypatch.delenv("NOVALTON_BYOK_KEYRING", raising=False)
    monkeypatch.setenv("NOVALTON_BYOK_ACTIVE_KEY_ID", "v1")
    with pytest.raises(VaultUnavailable):
        Keyring.from_environment()
