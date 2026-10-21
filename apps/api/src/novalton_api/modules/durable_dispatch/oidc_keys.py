"""Bounded issuer-pinned JWKS retrieval for the operator ID-token verifier."""

import asyncio
import json
import time
from threading import Lock
from urllib.parse import urlsplit

import httpx
import jwt

from novalton_api.core.exceptions import ApplicationError

_lock = Lock()
_cached_uri: str | None = None
_cached_until = 0.0
_cached_keys: dict[str, object] = {}
_next_unknown_refresh = 0.0
_fetching_uris: set[str] = set()


def _invalid() -> ApplicationError:
    return ApplicationError(
        "operator_session_invalid", "Operator session unavailable", status_code=401
    )


def _valid_uri(issuer: str, jwks_uri: str) -> bool:
    try:
        source, keys = urlsplit(issuer), urlsplit(jwks_uri)
        return (
            source.scheme == keys.scheme == "https"
            and source.netloc == keys.netloc
            and bool(keys.path)
            and not (keys.username or keys.password or keys.query or keys.fragment)
        )
    except ValueError:
        return False


async def _fetch(uri: str) -> dict[str, object]:
    try:
        async with (
            httpx.AsyncClient(timeout=5, follow_redirects=False) as client,
            client.stream("GET", uri, headers={"Accept": "application/json"}) as response,
        ):
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    raise ValueError("JWKS too large")
        payload = json.loads(body)
        raw_keys = payload["keys"]
        if not isinstance(raw_keys, list) or len(raw_keys) > 32:
            raise ValueError("Invalid JWKS")
        keys: dict[str, object] = {}
        for candidate in raw_keys:
            if not isinstance(candidate, dict):
                raise ValueError("Invalid JWKS key")
            kid = candidate.get("kid")
            if (
                candidate.get("kty") != "RSA"
                or candidate.get("alg", "RS256") != "RS256"
                or candidate.get("use", "sig") != "sig"
            ):
                continue
            if not isinstance(kid, str) or not 1 <= len(kid) <= 128 or kid in keys:
                raise ValueError("Invalid JWKS key")
            keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(candidate)
        return keys
    except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError) as exc:
        raise _invalid() from exc


async def signing_key(*, issuer: str, jwks_uri: str, token: str) -> object:
    if not _valid_uri(issuer, jwks_uri):
        raise _invalid()
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
            raise _invalid()
    except (jwt.PyJWTError, ValueError) as exc:
        raise _invalid() from exc
    global _cached_uri, _cached_until, _cached_keys, _next_unknown_refresh
    with _lock:
        now = time.monotonic()
        unknown = kid not in _cached_keys
        waiting = jwks_uri in _fetching_uris
        refresh = not waiting and (
            _cached_uri != jwks_uri
            or now >= _cached_until
            or (unknown and now >= _next_unknown_refresh)
        )
        if refresh:
            _fetching_uris.add(jwks_uri)
            if unknown:
                _next_unknown_refresh = now + 5
    if waiting:
        deadline = time.monotonic() + 5.5
        while True:
            with _lock:
                if jwks_uri not in _fetching_uris:
                    break
            if time.monotonic() >= deadline:
                raise _invalid()
            await asyncio.sleep(0.01)
    elif refresh:
        try:
            keys = await _fetch(jwks_uri)
            with _lock:
                _cached_uri, _cached_keys, _cached_until = jwks_uri, keys, time.monotonic() + 60
        finally:
            with _lock:
                _fetching_uris.discard(jwks_uri)
    with _lock:
        key = (
            _cached_keys.get(kid)
            if _cached_uri == jwks_uri and time.monotonic() < _cached_until
            else None
        )
        if key is None:
            raise _invalid()
        return key
