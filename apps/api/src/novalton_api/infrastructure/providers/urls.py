"""Provider endpoint validation kept independent from provider payloads."""

from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit


def _is_loopback(hostname: str) -> bool:
    if hostname.casefold() == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_provider_base_url(value: str) -> str:
    """Require HTTPS except for explicit loopback development endpoints."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("invalid provider base URL") from None
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.scheme not in {"http", "https"}
        or (parsed.scheme == "http" and not _is_loopback(parsed.hostname))
    ):
        raise ValueError("invalid provider base URL")
    netloc = parsed.hostname
    if ":" in netloc:
        netloc = f"[{netloc}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))
