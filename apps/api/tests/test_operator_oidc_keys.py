"""Issuer-pinned JWKS rotation, unknown-key throttling and signature enforcement."""

import asyncio
from datetime import UTC, datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.durable_dispatch import oidc_keys

ISSUER = "https://identity.example.test/"
URI = "https://identity.example.test/jwks"


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key, kid):
    now = int(datetime.now(UTC).timestamp())
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": "operator",
            "sub": "human",
            "iat": now,
            "auth_time": now - 60,
            "exp": now + 600,
        },
        key,
        algorithm="RS256",
        headers={"kid": kid},
    )


def test_jwks_rotation_and_strict_issuer(monkeypatch):
    first, second = _key(), _key()
    published = {"old": first.public_key()}
    calls = []

    async def fetch(uri):
        calls.append(uri)
        return dict(published)

    monkeypatch.setattr(oidc_keys, "_fetch", fetch)
    monkeypatch.setattr(oidc_keys, "_cached_uri", None)

    async def run():
        old_token = _token(first, "old")
        old = await oidc_keys.signing_key(issuer=ISSUER, jwks_uri=URI, token=old_token)
        assert jwt.decode(old_token, old, algorithms=["RS256"], audience="operator")
        published["new"] = second.public_key()
        monkeypatch.setattr(oidc_keys, "_next_unknown_refresh", 0)
        new_token = _token(second, "new")
        new = await oidc_keys.signing_key(issuer=ISSUER, jwks_uri=URI, token=new_token)
        assert jwt.decode(new_token, new, algorithms=["RS256"], audience="operator")
        assert len(calls) == 2
        for uri in (
            "http://identity.example.test/jwks",
            "https://other.test/jwks",
            "https://identity.example.test@other.test/jwks",
        ):
            with pytest.raises(ApplicationError):
                await oidc_keys.signing_key(issuer=ISSUER, jwks_uri=uri, token=old_token)
        with pytest.raises(ApplicationError):
            await oidc_keys.signing_key(
                issuer=ISSUER, jwks_uri=URI, token=_token(_key(), "unknown")
            )
        assert len(calls) == 2  # Unknown kids cannot trigger unbounded fetches.

    asyncio.run(run())


def test_jwks_rejects_malformed_or_unsigned_keys(monkeypatch):
    monkeypatch.setattr(oidc_keys, "_cached_uri", None)
    key = _key()

    async def invalid(_uri):
        raise ApplicationError(
            "operator_session_invalid", "Operator session unavailable", status_code=401
        )

    monkeypatch.setattr(oidc_keys, "_fetch", invalid)

    async def run():
        with pytest.raises(ApplicationError):
            await oidc_keys.signing_key(issuer=ISSUER, jwks_uri=URI, token=_token(key, "bad"))
        with pytest.raises(ApplicationError):
            await oidc_keys.signing_key(issuer=ISSUER, jwks_uri=URI, token="not.a.jwt")

    asyncio.run(run())
